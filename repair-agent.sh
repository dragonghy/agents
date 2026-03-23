#!/bin/bash
set -euo pipefail

# repair-agent.sh — Repair a broken agent by starting a fresh session
# with context recovered from the old session's JSONL log and journal.
#
# Usage: ./repair-agent.sh <agent-name>
# Example: ./repair-agent.sh product-lisa

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="${ROOT_DIR}/agent-config.py"

# Load environment variables
if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  source "${ROOT_DIR}/.env"
  set +a
fi

TMUX_SESSION="$(python3 "$CONFIG" tmux-session)"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <agent-name>"
  echo "Repairs a broken agent by starting a fresh session with context from the old one."
  exit 1
fi

AGENT="$1"
AGENT_DIR="${ROOT_DIR}/agents/${AGENT}"
AGENT_DEF="${ROOT_DIR}/.claude/agents/${AGENT}.md"

if [[ ! -d "$AGENT_DIR" ]]; then
  echo "ERROR: Agent directory not found: ${AGENT_DIR}"
  exit 1
fi

if [[ ! -f "$AGENT_DEF" ]]; then
  echo "ERROR: Agent definition not found: ${AGENT_DEF}"
  exit 1
fi

echo "=== Repairing agent: ${AGENT} ==="

# --- Step 1: Get old session ID ---
OLD_SID="$(python3 "$CONFIG" get-session "$AGENT")"
echo "  Old session ID: ${OLD_SID:-'(none)'}"

# --- Step 2: Extract context from old session ---
CONTEXT_FILE=$(mktemp)
trap "rm -f $CONTEXT_FILE" EXIT

# Find the JSONL file for the old session
# Claude Code stores session data in ~/.claude/projects/<project-path>/<session-id>.jsonl
JSONL_FOUND=""
for candidate_dir in "$HOME"/.claude/projects/*/; do
  if [[ -n "$OLD_SID" && -f "${candidate_dir}${OLD_SID}.jsonl" ]]; then
    JSONL_FOUND="${candidate_dir}${OLD_SID}.jsonl"
    break
  fi
done

if [[ -n "$JSONL_FOUND" ]]; then
  echo "  Found session log: ${JSONL_FOUND}"
  echo "  Extracting last meaningful messages..."

  # Extract last 20 meaningful human/assistant messages (skip error loops)
  python3 - "$JSONL_FOUND" "$CONTEXT_FILE" <<'PYEOF'
import json, sys

jsonl_path = sys.argv[1]
output_path = sys.argv[2]

messages = []
with open(jsonl_path, 'r') as f:
    for line in f:
        try:
            obj = json.loads(line.strip())
            if obj.get('type') == 'user':
                content = obj['message'].get('content', '')
                if isinstance(content, str) and content.strip():
                    # Skip error loops and dispatch spam
                    if 'tool use concurrency' in content:
                        continue
                    if '未读消息' in content and len(content) < 200:
                        continue
                    if '长时间处于进行中' in content and len(content) < 300:
                        continue
                    ts = obj.get('timestamp', '')
                    messages.append(f'[{ts}] Human: {content[:500]}')
        except:
            pass

# Keep last 15 meaningful messages
recent = messages[-15:]

# Also find the last session continuation summary if any
summaries = []
with open(jsonl_path, 'r') as f:
    for line in f:
        try:
            obj = json.loads(line.strip())
            if obj.get('type') == 'user':
                content = obj['message'].get('content', '')
                if isinstance(content, str) and 'session is being continued' in content.lower():
                    summaries.append(content[:2000])
        except:
            pass

with open(output_path, 'w') as f:
    if summaries:
        f.write("## 最近的 Session Summary\n\n")
        f.write(summaries[-1][:1500])
        f.write("\n\n")

    f.write("## 最近的对话记录\n\n")
    for msg in recent:
        f.write(msg + "\n\n")

print(f'  Extracted {len(recent)} messages' + (f' + 1 session summary' if summaries else ''))
PYEOF
else
  echo "  No session log found for old session"
  echo "(no previous session log found)" > "$CONTEXT_FILE"
fi

# Add latest journal entries
JOURNAL_DIR="${AGENT_DIR}/journal"
if [[ -d "$JOURNAL_DIR" ]]; then
  LATEST_JOURNAL="$(ls -t "$JOURNAL_DIR"/*.md 2>/dev/null | head -1)"
  if [[ -n "$LATEST_JOURNAL" ]]; then
    echo "  Adding latest journal: $(basename "$LATEST_JOURNAL")"
    echo "" >> "$CONTEXT_FILE"
    echo "## 最近的工作日志 ($(basename "$LATEST_JOURNAL"))" >> "$CONTEXT_FILE"
    echo "" >> "$CONTEXT_FILE"
    head -60 "$LATEST_JOURNAL" >> "$CONTEXT_FILE"
  fi
fi

# --- Step 3: Kill existing broken session ---
echo "  Stopping broken session..."
# Kill ALL windows with this agent's name (there might be duplicates)
KILLED=0
while true; do
  WIN_IDX="$(tmux list-windows -t "$TMUX_SESSION" -F '#{window_index} #{window_name}' 2>/dev/null \
    | grep " ${AGENT}$" | head -1 | awk '{print $1}' || true)"
  if [[ -z "$WIN_IDX" ]]; then
    break
  fi
  tmux kill-window -t "$TMUX_SESSION:${WIN_IDX}" 2>/dev/null || true
  KILLED=$((KILLED + 1))
  sleep 0.5
done
if [[ $KILLED -gt 0 ]]; then
  echo "  Killed $KILLED window(s) for $AGENT"
else
  echo "  No existing window found"
fi

# --- Step 4: Auto-generate workspaces ---
echo "  Running setup-agents.py..."
python3 "${ROOT_DIR}/setup-agents.py" 2>/dev/null

# --- Step 5: Start fresh session (NO --resume) ---
echo "  Starting fresh session..."

# Build --add-dir flags
ADD_DIR_FLAGS=""
while IFS= read -r dir; do
  [[ -n "$dir" ]] && ADD_DIR_FLAGS="${ADD_DIR_FLAGS} --add-dir ${dir}"
done < <(python3 "$CONFIG" get-add-dirs "$AGENT")

AGENT_FLAG="--agent ${AGENT}"
CMD="cd ${ROOT_DIR}/agents/${AGENT} && claude --dangerously-skip-permissions ${AGENT_FLAG}${ADD_DIR_FLAGS}"

# Ensure tmux session exists
if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
  tmux new-session -d -s "$TMUX_SESSION" -n "_init"
fi

tmux new-window -t "$TMUX_SESSION" -n "$AGENT"
tmux send-keys -t "$TMUX_SESSION:$AGENT" "$CMD" Enter
echo "  Fresh session starting..."

# --- Step 6: Wait for Claude Code to be ready ---
echo "  Waiting for Claude Code to initialize (20s)..."
sleep 20

# --- Step 7: Detect and save new session ID ---
echo "  Detecting new session ID..."
NEW_SID="$(python3 "$CONFIG" detect-session "$AGENT")"
if [[ -n "$NEW_SID" ]]; then
  python3 "$CONFIG" set-session "$AGENT" "$NEW_SID"
  echo "  New session ID: ${NEW_SID}"
else
  echo "  WARNING: Could not detect new session ID yet"
fi

# --- Step 8: Send context restoration message ---
echo "  Sending context restoration message..."
CONTEXT="$(cat "$CONTEXT_FILE")"

# Build the restoration prompt
# Key: tell agent to READ the old session log and journal files FIRST,
# not just glance at the summary we paste here.
RESTORE_MSG="⚠️ 重要：你的前一个 session 因为 'tool use concurrency' 错误损坏了，已被替换为这个新 session。

你的旧 session ID 是：${OLD_SID}
旧 session 的 JSONL 日志文件位于：${JSONL_FOUND:-'(未找到)'}

## 第一步：恢复上下文（必须先完成，不要跳过）

请按以下顺序恢复你的知识和记忆：

1. **阅读你的 journal 日志**：读取 ${JOURNAL_DIR}/ 目录下最近 2-3 个日志文件，了解你过去几天的工作内容、关键决策和待办事项。

2. **阅读旧 session 的最后 20 条消息**：从旧 session 的 JSONL 文件中提取最后 20 条有意义的消息（跳过 error loop），理解你被中断时正在做什么。你可以用以下命令：
   \`\`\`
   tail -c 100000 '${JSONL_FOUND:-}' | python3 -c \"import json,sys; [print(json.loads(l)['message']['content'][:300]) for l in sys.stdin if 'user' == json.loads(l).get('type','') and 'concurrency' not in json.loads(l).get('message',{}).get('content','')]\" 2>/dev/null | tail -20
   \`\`\`

3. **阅读以下摘要信息**（作为补充参考）：

${CONTEXT}

## 第二步：确认你已恢复上下文

在完成第一步后，请用 1-2 段话总结：
- 你是谁、你负责什么项目
- 你之前最近在做的工作是什么
- 有哪些未完成的任务

## 第三步：恢复工作

确认上下文后，再执行：
1. 检查收件箱：get_inbox(agent_id=\"${AGENT}\")
2. 检查待处理任务（assignee=\"${AGENT}\"，status=3,4）
3. 如果有未完成的工作，继续推进"

# Write to temp file for safe tmux send
PROMPT_FILE=$(mktemp)
echo "$RESTORE_MSG" > "$PROMPT_FILE"

# Send via tmux - paste from file to avoid shell escaping issues
tmux load-buffer "$PROMPT_FILE" 2>/dev/null
tmux paste-buffer -t "$TMUX_SESSION:$AGENT" 2>/dev/null
sleep 1
tmux send-keys -t "$TMUX_SESSION:$AGENT" Enter
rm -f "$PROMPT_FILE"

echo ""
echo "=== Repair complete for ${AGENT} ==="
echo "  Old session: ${OLD_SID:-'(none)'}"
echo "  New session: ${NEW_SID:-'(pending detection)'}"
echo "  Context restored from: session log + journal"
echo ""
echo "  Check: tmux select-window -t ${TMUX_SESSION}:${AGENT}"
