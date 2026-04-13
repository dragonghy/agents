"""Regression tests for setup-agents.py v2 behavior.

Verifies:
- V2 agent type prompts are synced from templates/v2/ to .claude/agents/.
- Non-dispatchable v1 agents are skipped (no workspace scaffolding).
- Name collisions between v1 agents and v2 types are resolved in favor of v2.
- templates/v2/*.md files are never written to by the script.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "setup-agents.py")


def _md5(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


class SetupAgentsV2Test(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="setup-agents-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # Snapshot templates/v2/ so we can detect any illegal writes.
        self.v2_dir = os.path.join(ROOT, "templates", "v2")
        self.v2_snapshot = {
            name: _md5(os.path.join(self.v2_dir, name))
            for name in os.listdir(self.v2_dir)
            if name.endswith(".md")
        }

    def run_setup(self) -> str:
        result = subprocess.run(
            [sys.executable, SCRIPT, "--output-dir", self.tmp],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return result.stdout

    def test_v2_agent_types_synced(self) -> None:
        self.run_setup()
        for name in ("development", "operations", "assistant"):
            src = os.path.join(self.v2_dir, f"{name}.md")
            dst = os.path.join(self.tmp, ".claude", "agents", f"{name}.md")
            self.assertTrue(os.path.isfile(dst), f"{dst} missing")
            self.assertEqual(_md5(src), _md5(dst), f"{name} content mismatch")

    def test_non_dispatchable_agents_skipped(self) -> None:
        stdout = self.run_setup()
        # Frozen v1 agents should not get workspace dirs.
        for frozen in ("dev-emma", "qa-oliver", "user-sophia", "product-kevin"):
            self.assertIn(f"{frozen}: SKIP", stdout)
            agent_dir = os.path.join(self.tmp, "agents", frozen)
            self.assertFalse(
                os.path.isdir(agent_dir),
                f"{agent_dir} should not have been created",
            )

    def test_dispatchable_agents_kept(self) -> None:
        self.run_setup()
        for active in ("admin", "ops", "dev-alex", "qa-lucy"):
            agent_dir = os.path.join(self.tmp, "agents", active)
            self.assertTrue(
                os.path.isfile(os.path.join(agent_dir, ".mcp.json")),
                f"{active} .mcp.json should exist",
            )

    def test_v1_assistant_shadowed_by_v2_type(self) -> None:
        stdout = self.run_setup()
        self.assertIn("assistant: SKIP (shadowed by v2 agent type)", stdout)
        # The v2 assistant prompt should be the one that lands in .claude/agents/.
        v2_src = os.path.join(self.v2_dir, "assistant.md")
        out = os.path.join(self.tmp, ".claude", "agents", "assistant.md")
        self.assertEqual(_md5(v2_src), _md5(out))

    def test_templates_v2_not_written(self) -> None:
        self.run_setup()
        after = {
            name: _md5(os.path.join(self.v2_dir, name))
            for name in os.listdir(self.v2_dir)
            if name.endswith(".md")
        }
        self.assertEqual(self.v2_snapshot, after)


if __name__ == "__main__":
    unittest.main()
