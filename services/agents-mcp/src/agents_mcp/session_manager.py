"""V2 Session Manager: Task-driven, ephemeral agent sessions.

Replaces the v1 model of 18 persistent agents with on-demand session spawning.
Sessions are created per-task, run until completion, then released.

Key concepts:
- Agent Type: template defining thinking mode + tools + permissions (dev/ops/assistant)
- Session Slot: a tmux window running one Claude Code instance
- Session Pool: bounded set of concurrent slots (default: 4)
- Task: the unit of work that triggers session creation
"""

import asyncio
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Session pool configuration
MAX_CONCURRENT_SESSIONS = 4
SESSION_IDLE_TIMEOUT = 300  # 5 min idle → release session
SESSION_CHECK_INTERVAL = 15  # seconds between idle checks

_SUBPROCESS_TIMEOUT = 10


@dataclass
class SessionInfo:
    """Tracks a running agent session."""
    session_id: str          # unique ID for this session (e.g., "dev-001")
    agent_type: str          # "development", "operations", "assistant"
    task_id: Optional[int]   # ticket ID being worked on
    project: Optional[str]   # project name
    tmux_window: str         # tmux window name
    started_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    status: str = "starting"  # starting, active, idle, releasing


class SessionManager:
    """Manages a pool of ephemeral agent sessions."""

    def __init__(
        self,
        tmux_session: str = "agents",
        root_dir: str = ".",
        max_sessions: int = MAX_CONCURRENT_SESSIONS,
        project_config: dict = None,
    ):
        self.tmux_session = tmux_session
        self.root_dir = root_dir
        self.max_sessions = max_sessions
        self._project_config = project_config or {}
        self._sessions: dict[str, SessionInfo] = {}  # session_id → SessionInfo
        self._next_id = 1
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        return len([s for s in self._sessions.values() if s.status in ("starting", "active")])

    @property
    def has_capacity(self) -> bool:
        return self.active_count < self.max_sessions

    def get_sessions(self) -> list[dict]:
        """Return all sessions as dicts for API/monitoring."""
        return [
            {
                "session_id": s.session_id,
                "agent_type": s.agent_type,
                "task_id": s.task_id,
                "project": s.project,
                "tmux_window": s.tmux_window,
                "started_at": s.started_at,
                "last_active_at": s.last_active_at,
                "status": s.status,
                "uptime_seconds": int(time.time() - s.started_at),
            }
            for s in self._sessions.values()
        ]

    async def spawn_session(
        self,
        agent_type: str,
        task_id: int,
        task_description: str,
        project: Optional[str] = None,
        project_dirs: Optional[list[str]] = None,
    ) -> Optional[SessionInfo]:
        """Spawn a new agent session for a task.

        Args:
            agent_type: "development", "operations", or "assistant"
            task_id: Ticket ID to work on
            task_description: Human-readable task description (sent as first message)
            project: Project name (for loading project-specific context)
            project_dirs: Additional directories to add to the session

        Returns:
            SessionInfo if spawned, None if no capacity
        """
        async with self._lock:
            if not self.has_capacity:
                logger.warning(
                    f"No session capacity ({self.active_count}/{self.max_sessions}). "
                    f"Cannot spawn {agent_type} for task #{task_id}"
                )
                return None

            session_id = f"{agent_type[:3]}-{self._next_id:03d}"
            self._next_id += 1

            # Map agent type to agent definition file
            agent_def = self._resolve_agent_def(agent_type)
            if not agent_def:
                logger.error(f"No agent definition found for type: {agent_type}")
                return None

            info = SessionInfo(
                session_id=session_id,
                agent_type=agent_type,
                task_id=task_id,
                project=project,
                tmux_window=session_id,
            )
            self._sessions[session_id] = info

        # Spawn tmux window and start Claude Code (outside lock)
        try:
            self._create_tmux_window(info, agent_def, project_dirs)
            # Wait for Claude Code to start, then send the task
            await asyncio.sleep(5)
            self._send_task(info, task_description, task_id)
            info.status = "active"
            logger.info(
                f"Spawned session {session_id} ({agent_type}) for task #{task_id}"
                + (f" [project: {project}]" if project else "")
            )
            return info
        except Exception as e:
            logger.error(f"Failed to spawn session {session_id}: {e}")
            info.status = "releasing"
            await self.release_session(session_id)
            return None

    def _resolve_agent_def(self, agent_type: str) -> Optional[str]:
        """Find the agent definition file for a type."""
        # v2 agent types live in templates/v2/
        v2_path = os.path.join(self.root_dir, "templates", "v2", f"{agent_type}.md")
        if os.path.isfile(v2_path):
            return agent_type  # Claude Code --agent flag uses the name

        # Fallback: check .claude/agents/ directory
        agents_dir = os.path.join(self.root_dir, ".claude", "agents")
        agent_md = os.path.join(agents_dir, f"{agent_type}.md")
        if os.path.isfile(agent_md):
            return agent_type

        return None

    def _resolve_project_dir(self, project: Optional[str]) -> str:
        """Determine the working directory for a session.

        Claude Code automatically loads claude.md from the working directory,
        so cd-ing into the right project dir is how we inject project context.
        """
        if project and self._project_config:
            proj_cfg = self._project_config.get(project, {})
            path = proj_cfg.get("path", "")
            if path:
                # Resolve relative paths against root_dir
                if not os.path.isabs(path):
                    path = os.path.join(self.root_dir, path)
                if os.path.isdir(path):
                    return path
        return self.root_dir

    def _create_tmux_window(
        self,
        info: SessionInfo,
        agent_def: str,
        project_dirs: Optional[list[str]] = None,
    ):
        """Create a tmux window and start Claude Code.

        Context assembly (per RETROSPECTIVE §4.3):
        1. Agent type's system prompt → --agent flag loads from .claude/agents/<type>.md
        2. Global skills → accessible via --add-dir to repo root (templates/shared/skills/)
        3. Project claude.md → loaded automatically by Claude Code from working directory
        4. Project skills → accessible via --add-dir to project path
        5. Task context → sent as first message after startup (in _send_task)
        """
        # Working directory = project dir (so Claude Code loads project's claude.md)
        work_dir = self._resolve_project_dir(info.project)

        # Always add the agent repo root for access to global skills and daemon config
        add_dir_flags = f" --add-dir {self.root_dir}"
        if project_dirs:
            for d in project_dirs:
                if os.path.isdir(d) and d != self.root_dir:
                    add_dir_flags += f" --add-dir {d}"

        cmd = (
            f"cd {work_dir} && "
            f"claude --dangerously-skip-permissions "
            f"--agent {agent_def}"
            f"{add_dir_flags}"
        )

        subprocess.check_call(
            ["tmux", "new-window", "-t", self.tmux_session, "-n", info.tmux_window],
            timeout=_SUBPROCESS_TIMEOUT,
        )
        subprocess.check_call(
            ["tmux", "send-keys", "-t", f"{self.tmux_session}:{info.tmux_window}", cmd, "Enter"],
            timeout=_SUBPROCESS_TIMEOUT,
        )

    def _send_task(self, info: SessionInfo, description: str, task_id: int):
        """Send the task to the agent session.

        The message instructs the agent to:
        1. Read the full ticket (description + all comments) for context recovery
        2. Read the project's claude.md for project conventions
        3. Start working according to the ticket's phase
        """
        msg = (
            f"你的任务是 ticket #{task_id}。\n\n"
            f"**第一步**：调用 get_ticket(ticket_id={task_id}) 读取完整 ticket 信息，"
            f"然后调用 get_comments(module=\"ticket\", module_id={task_id}, limit=0) 读取所有历史评论。"
            f"评论中包含之前的工作记录、Human 反馈和决策——你必须全部阅读后再开始工作。\n\n"
            f"**第二步**：阅读当前目录下的 claude.md 了解项目背景和约定。\n\n"
            f"**第三步**：根据 ticket 的 phase（plan/implement/test/deliver）进入对应的思考模式开始工作。"
            f"如果 ticket 没有 phase 字段，从 ticket 描述推断应该进入哪个阶段。\n\n"
            f"任务概要: {description}"
        )
        try:
            subprocess.check_call(
                [
                    "tmux", "send-keys", "-l",
                    "-t", f"{self.tmux_session}:{info.tmux_window}",
                    msg,
                ],
                timeout=_SUBPROCESS_TIMEOUT,
            )
            subprocess.check_call(
                [
                    "tmux", "send-keys",
                    "-t", f"{self.tmux_session}:{info.tmux_window}",
                    "Enter",
                ],
                timeout=_SUBPROCESS_TIMEOUT,
            )
        except Exception as e:
            logger.warning(f"Failed to send task to {info.session_id}: {e}")

    def is_session_idle(self, session_id: str) -> bool:
        """Check if a session is idle (at the ❯ prompt, not processing)."""
        info = self._sessions.get(session_id)
        if not info:
            return False

        try:
            out = subprocess.check_output(
                [
                    "tmux", "capture-pane", "-t",
                    f"{self.tmux_session}:{info.tmux_window}",
                    "-p", "-S", "-5",
                ],
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
            lines = out.strip().split("\n")

            # Check for "esc to interrupt" = agent is working
            for line in lines:
                if "esc to interrupt" in line.lower():
                    info.last_active_at = time.time()
                    return False

            # Check for ❯ prompt = idle
            for line in lines:
                if "❯" in line:
                    return True

            return False
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    async def release_session(self, session_id: str):
        """Release (destroy) a session."""
        info = self._sessions.get(session_id)
        if not info:
            return

        info.status = "releasing"
        try:
            # Send /exit to Claude Code
            subprocess.run(
                [
                    "tmux", "send-keys",
                    "-t", f"{self.tmux_session}:{info.tmux_window}",
                    "/exit", "Enter",
                ],
                timeout=_SUBPROCESS_TIMEOUT,
                capture_output=True,
            )
            await asyncio.sleep(2)

            # Kill the tmux window
            subprocess.run(
                [
                    "tmux", "kill-window",
                    "-t", f"{self.tmux_session}:{info.tmux_window}",
                ],
                timeout=_SUBPROCESS_TIMEOUT,
                capture_output=True,
            )
        except Exception as e:
            logger.warning(f"Error releasing session {session_id}: {e}")

        del self._sessions[session_id]
        logger.info(f"Released session {session_id}")

    async def monitor_loop(self):
        """Background loop to monitor sessions and release idle ones."""
        logger.info("Session monitor started")
        while True:
            try:
                now = time.time()
                to_release = []

                for sid, info in list(self._sessions.items()):
                    if info.status == "releasing":
                        continue

                    if self.is_session_idle(sid):
                        idle_time = now - info.last_active_at
                        if idle_time > SESSION_IDLE_TIMEOUT:
                            logger.info(
                                f"Session {sid} idle for {int(idle_time)}s, releasing"
                            )
                            to_release.append(sid)

                for sid in to_release:
                    await self.release_session(sid)

            except Exception as e:
                logger.error(f"Session monitor error: {e}")

            await asyncio.sleep(SESSION_CHECK_INTERVAL)
