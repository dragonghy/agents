"""Tests for ``_find_project_root`` (project-root marker detection).

Regression coverage for ticket #42 — when PR #33 (Phase 5a v1
infrastructure cleanup) deleted ``setup-agents.py``, the legacy marker
this function relied on disappeared, and the daemon fell back to CWD
which made ``profiles/`` resolve to a non-existent path. The fix
switched to ``agents.yaml`` / ``profiles/`` as markers, both of which
are stable across the cleanup.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch


class TestFindProjectRoot:
    def _import_with_fake_pkg_dir(self, fake_pkg_dir: Path):
        """Import ``_find_project_root`` with patched ``__file__``.

        The function inspects its own module's ``__file__`` to compute a
        candidate root four levels up. To exercise the walk-from-CWD
        branch in isolation, we point ``__file__`` at a path under a
        directory that contains no project markers.
        """
        from agents_mcp import server as srv

        return srv, fake_pkg_dir

    def test_finds_root_via_agents_yaml(self, tmp_path, monkeypatch):
        """A directory with ``agents.yaml`` is recognized as project root."""
        from agents_mcp import server as srv

        (tmp_path / "agents.yaml").write_text("agents: {}\n")
        # Park the package candidate four levels deep under a no-marker
        # parent so the from-__file__ branch returns a path without
        # markers, forcing the walk-from-CWD branch to take over.
        empty = tmp_path.parent / "empty-pkg-tree"
        empty.mkdir(exist_ok=True)
        fake_file = empty / "a/b/c/d/server.py"
        fake_file.parent.mkdir(parents=True, exist_ok=True)

        monkeypatch.chdir(tmp_path)
        with patch.object(srv, "__file__", str(fake_file)):
            assert os.path.realpath(srv._find_project_root()) == os.path.realpath(
                str(tmp_path)
            )

    def test_finds_root_via_profiles_dir(self, tmp_path, monkeypatch):
        """A directory with ``profiles/`` (and no agents.yaml) is also root."""
        from agents_mcp import server as srv

        (tmp_path / "profiles").mkdir()
        empty = tmp_path.parent / "empty-pkg-tree2"
        empty.mkdir(exist_ok=True)
        fake_file = empty / "a/b/c/d/server.py"
        fake_file.parent.mkdir(parents=True, exist_ok=True)

        monkeypatch.chdir(tmp_path)
        with patch.object(srv, "__file__", str(fake_file)):
            assert os.path.realpath(srv._find_project_root()) == os.path.realpath(
                str(tmp_path)
            )

    def test_setup_agents_py_alone_is_not_root(self, tmp_path, monkeypatch):
        """The retired ``setup-agents.py`` marker no longer triggers detection.

        Guards against re-introducing the old marker by accident.
        """
        from agents_mcp import server as srv

        (tmp_path / "setup-agents.py").write_text("# legacy stub\n")
        empty = tmp_path.parent / "empty-pkg-tree3"
        empty.mkdir(exist_ok=True)
        fake_file = empty / "a/b/c/d/server.py"
        fake_file.parent.mkdir(parents=True, exist_ok=True)

        monkeypatch.chdir(tmp_path)
        with patch.object(srv, "__file__", str(fake_file)):
            # Should NOT detect tmp_path — only setup-agents.py is present
            # and that marker is no longer recognized. Walk falls through
            # to the CWD-fallback branch returning os.path.abspath(".").
            # That fallback IS tmp_path here (since we chdir'd into it),
            # but it returns it as a fallback, not as a recognized root.
            # To verify the marker rejection, instead check that the
            # function does not recognize a sibling no-marker dir as root
            # when CWD walks up past it.
            sibling = tmp_path / "child"
            sibling.mkdir()
            monkeypatch.chdir(sibling)
            result = srv._find_project_root()
            # Walk from sibling: sibling has nothing; tmp_path has only
            # setup-agents.py (rejected); walks further up and ultimately
            # falls back to os.path.abspath(".") which is sibling.
            # The PASS condition is that result != tmp_path (the marker
            # was correctly rejected).
            assert os.path.realpath(result) != os.path.realpath(str(tmp_path))

    def test_walks_up_to_find_root(self, tmp_path, monkeypatch):
        """When CWD is a subdir, walk up until a marker is found."""
        from agents_mcp import server as srv

        (tmp_path / "agents.yaml").write_text("agents: {}\n")
        sub = tmp_path / "deeply" / "nested" / "subdir"
        sub.mkdir(parents=True)

        empty = tmp_path.parent / "empty-pkg-tree4"
        empty.mkdir(exist_ok=True)
        fake_file = empty / "a/b/c/d/server.py"
        fake_file.parent.mkdir(parents=True, exist_ok=True)

        monkeypatch.chdir(sub)
        with patch.object(srv, "__file__", str(fake_file)):
            assert os.path.realpath(srv._find_project_root()) == os.path.realpath(
                str(tmp_path)
            )
