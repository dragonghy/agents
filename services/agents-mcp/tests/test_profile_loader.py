"""Tests for the Profile loader.

Hermetic: builds synthetic profile.md files in tmp_path and a fresh AgentStore
on a tmp sqlite DB. No real profiles/ dir, no SDK, no network.

Style mirrors test_orchestration_session.py — sync test functions wrapping
async coroutines via a local ``run()`` helper, so we don't need
pytest-asyncio.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agents_mcp.adapters.base import Profile, ProfileParseError
from agents_mcp.profile_loader import ProfileLoader, load_profile
from agents_mcp.store import AgentStore


# ── Fixtures / helpers ──


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test-profile-loader.db")


@pytest.fixture
def profiles_dir(tmp_path):
    d = tmp_path / "profiles"
    d.mkdir()
    return d


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _make_store(db_path: str) -> AgentStore:
    s = AgentStore(db_path)
    await s.initialize()
    return s


def _write_profile(
    profiles_dir: Path,
    name: str,
    body: str = "You are a test agent. Do test things.\n",
    description: str = "Test profile for unit tests.",
    runner_type: str = "claude-sonnet-4.6",
    mcp_servers: list[str] | None = None,
    skills: list[str] | None = None,
) -> Path:
    """Write a well-formed profile.md and return its path."""
    d = profiles_dir / name
    d.mkdir(parents=True, exist_ok=True)
    md = d / "profile.md"
    fm_lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
        f"runner_type: {runner_type}",
    ]
    if mcp_servers is not None:
        fm_lines.append("mcp_servers:")
        for s in mcp_servers:
            fm_lines.append(f"  - {s}")
    if skills is not None:
        fm_lines.append("skills:")
        for s in skills:
            fm_lines.append(f"  - {s}")
    fm_lines.append("---")
    md.write_text("\n".join(fm_lines) + "\n\n" + body, encoding="utf-8")
    return md


# ── Parsing: load_profile ──


class TestLoadProfile:
    def test_valid_profile_returns_profile_dataclass(self, profiles_dir):
        _write_profile(
            profiles_dir,
            "developer",
            body="You write code. Carefully.\n",
            description="Implements code changes",
            mcp_servers=["agents", "agent-hub"],
            skills=["development-lifecycle"],
        )
        p = load_profile("developer", profiles_dir)

        assert isinstance(p, Profile)
        assert p.name == "developer"
        assert p.description == "Implements code changes"
        assert p.runner_type == "claude-sonnet-4.6"
        assert p.mcp_servers == ("agents", "agent-hub")
        assert p.skills == ("development-lifecycle",)
        assert "You write code" in p.system_prompt
        # file_hash is a hex sha256
        assert len(p.file_hash) == 64
        assert all(c in "0123456789abcdef" for c in p.file_hash)
        # file_path is absolute
        assert p.file_path.endswith("profile.md")
        assert Path(p.file_path).is_absolute()

    def test_optional_lists_default_to_empty(self, profiles_dir):
        _write_profile(profiles_dir, "secretary")  # no mcp_servers, no skills
        p = load_profile("secretary", profiles_dir)
        assert p.mcp_servers == ()
        assert p.skills == ()

    def test_missing_file_raises_filenotfound(self, profiles_dir):
        with pytest.raises(FileNotFoundError):
            load_profile("nonexistent", profiles_dir)

    def test_missing_opening_delimiter_raises(self, profiles_dir):
        d = profiles_dir / "broken"
        d.mkdir()
        (d / "profile.md").write_text(
            "name: broken\nrunner_type: claude\n---\nbody\n", encoding="utf-8"
        )
        with pytest.raises(ProfileParseError) as exc:
            load_profile("broken", profiles_dir)
        assert "opening frontmatter" in str(exc.value).lower()

    def test_missing_closing_delimiter_raises(self, profiles_dir):
        d = profiles_dir / "broken"
        d.mkdir()
        (d / "profile.md").write_text(
            "---\nname: broken\nrunner_type: claude\nbody-but-no-close\n",
            encoding="utf-8",
        )
        with pytest.raises(ProfileParseError) as exc:
            load_profile("broken", profiles_dir)
        assert "closing frontmatter" in str(exc.value).lower()

    def test_missing_runner_type_raises(self, profiles_dir):
        d = profiles_dir / "broken"
        d.mkdir()
        (d / "profile.md").write_text(
            "---\ndescription: present\n---\nbody\n", encoding="utf-8"
        )
        with pytest.raises(ProfileParseError) as exc:
            load_profile("broken", profiles_dir)
        assert "runner_type" in str(exc.value)

    def test_missing_description_raises(self, profiles_dir):
        d = profiles_dir / "broken"
        d.mkdir()
        (d / "profile.md").write_text(
            "---\nrunner_type: claude-sonnet-4.6\n---\nbody\n", encoding="utf-8"
        )
        with pytest.raises(ProfileParseError) as exc:
            load_profile("broken", profiles_dir)
        assert "description" in str(exc.value)

    def test_malformed_yaml_raises(self, profiles_dir):
        d = profiles_dir / "broken"
        d.mkdir()
        # Unclosed bracket → YAML parse error.
        (d / "profile.md").write_text(
            "---\ndescription: oops\nrunner_type: x\nmcp_servers: [\n---\nbody\n",
            encoding="utf-8",
        )
        with pytest.raises(ProfileParseError) as exc:
            load_profile("broken", profiles_dir)
        assert "yaml" in str(exc.value).lower()

    def test_empty_body_raises(self, profiles_dir):
        d = profiles_dir / "broken"
        d.mkdir()
        (d / "profile.md").write_text(
            "---\ndescription: x\nrunner_type: y\n---\n\n   \n", encoding="utf-8"
        )
        with pytest.raises(ProfileParseError) as exc:
            load_profile("broken", profiles_dir)
        assert "empty" in str(exc.value).lower()

    def test_mcp_servers_must_be_list_of_strings(self, profiles_dir):
        d = profiles_dir / "broken"
        d.mkdir()
        # mcp_servers as a single string instead of a list → reject.
        (d / "profile.md").write_text(
            "---\ndescription: x\nrunner_type: y\nmcp_servers: agents\n---\nbody\n",
            encoding="utf-8",
        )
        with pytest.raises(ProfileParseError) as exc:
            load_profile("broken", profiles_dir)
        assert "mcp_servers" in str(exc.value)

    def test_orchestration_tools_defaults_to_false(self, profiles_dir):
        # Profile with no orchestration_tools field → False.
        _write_profile(profiles_dir, "developer")
        p = load_profile("developer", profiles_dir)
        assert p.orchestration_tools is False

    def test_orchestration_tools_true_parses(self, profiles_dir):
        d = profiles_dir / "tpm"
        d.mkdir()
        (d / "profile.md").write_text(
            "---\n"
            "description: TPM\n"
            "runner_type: claude\n"
            "orchestration_tools: true\n"
            "---\n\n"
            "body\n",
            encoding="utf-8",
        )
        p = load_profile("tpm", profiles_dir)
        assert p.orchestration_tools is True

    def test_orchestration_tools_non_bool_rejected(self, profiles_dir):
        d = profiles_dir / "broken"
        d.mkdir()
        (d / "profile.md").write_text(
            "---\n"
            "description: x\n"
            "runner_type: y\n"
            "orchestration_tools: yes-string\n"
            "---\n\n"
            "body\n",
            encoding="utf-8",
        )
        with pytest.raises(ProfileParseError) as exc:
            load_profile("broken", profiles_dir)
        assert "orchestration_tools" in str(exc.value)

    def test_hash_is_stable_for_same_content(self, profiles_dir):
        _write_profile(profiles_dir, "twin")
        h1 = load_profile("twin", profiles_dir).file_hash
        h2 = load_profile("twin", profiles_dir).file_hash
        assert h1 == h2

    def test_hash_changes_with_content(self, profiles_dir):
        path = _write_profile(profiles_dir, "drift", body="version 1\n")
        h1 = load_profile("drift", profiles_dir).file_hash
        # Rewrite the body; hash must change.
        _write_profile(profiles_dir, "drift", body="version 2\n")
        h2 = load_profile("drift", profiles_dir).file_hash
        assert h1 != h2
        # Just make sure mtime / path are sane.
        assert path.exists()


# ── Scanning: ProfileLoader.scan() ──


class TestProfileLoaderScan:
    def test_scan_inserts_new_entries(self, profiles_dir, db_path):
        async def _t():
            store = await _make_store(db_path)
            _write_profile(profiles_dir, "tpm")
            _write_profile(profiles_dir, "developer")

            loader = ProfileLoader(profiles_dir, store)
            results = await loader.scan()

            # All loaded for the first time.
            actions = sorted(results)
            assert actions == [("developer", "loaded"), ("tpm", "loaded")]

            registry = await store.list_profile_registry()
            names = sorted(r["name"] for r in registry)
            assert names == ["developer", "tpm"]
            await store.close()

        run(_t())

    def test_scan_unchanged_on_second_pass(self, profiles_dir, db_path):
        async def _t():
            store = await _make_store(db_path)
            _write_profile(profiles_dir, "tpm")
            loader = ProfileLoader(profiles_dir, store)

            first = await loader.scan()
            assert first == [("tpm", "loaded")]

            second = await loader.scan()
            assert second == [("tpm", "unchanged")]

            # Registry row count stayed at 1.
            assert len(await store.list_profile_registry()) == 1
            await store.close()

        run(_t())

    def test_scan_detects_file_changes_via_hash(self, profiles_dir, db_path):
        async def _t():
            store = await _make_store(db_path)
            _write_profile(profiles_dir, "tpm", description="v1")
            loader = ProfileLoader(profiles_dir, store)

            await loader.scan()
            row1 = await store.get_profile_registry("tpm")
            hash1 = row1["file_hash"]

            # Rewrite with different content.
            _write_profile(profiles_dir, "tpm", description="v2 changed")
            second = await loader.scan()
            assert second == [("tpm", "updated")]

            row2 = await store.get_profile_registry("tpm")
            assert row2["file_hash"] != hash1
            assert row2["description"] == "v2 changed"
            await store.close()

        run(_t())

    def test_scan_skips_directories_without_profile_md(
        self, profiles_dir, db_path
    ):
        async def _t():
            store = await _make_store(db_path)
            _write_profile(profiles_dir, "tpm")
            # An empty subdir — must be ignored, not errored.
            (profiles_dir / "empty-dir").mkdir()
            # A loose file at the top level — must be ignored.
            (profiles_dir / "README.md").write_text("just a readme\n")

            loader = ProfileLoader(profiles_dir, store)
            results = await loader.scan()

            assert results == [("tpm", "loaded")]
            await store.close()

        run(_t())

    def test_scan_records_errored_for_malformed_profile(
        self, profiles_dir, db_path
    ):
        async def _t():
            store = await _make_store(db_path)
            _write_profile(profiles_dir, "good")
            # Malformed: missing closing delimiter.
            d = profiles_dir / "bad"
            d.mkdir()
            (d / "profile.md").write_text(
                "---\ndescription: x\nrunner_type: y\nbody-no-close\n",
                encoding="utf-8",
            )

            loader = ProfileLoader(profiles_dir, store)
            results = sorted(await loader.scan())

            assert results == [("bad", "errored"), ("good", "loaded")]

            # The errored profile should NOT appear in the registry.
            registry = await store.list_profile_registry()
            names = [r["name"] for r in registry]
            assert names == ["good"]
            await store.close()

        run(_t())

    def test_scan_when_profiles_dir_missing(self, tmp_path, db_path):
        async def _t():
            store = await _make_store(db_path)
            missing = tmp_path / "does-not-exist"
            loader = ProfileLoader(missing, store)
            assert await loader.scan() == []
            await store.close()

        run(_t())

    def test_scan_preserves_existing_row_when_new_version_is_malformed(
        self, profiles_dir, db_path
    ):
        async def _t():
            store = await _make_store(db_path)
            _write_profile(profiles_dir, "tpm", description="initial")
            loader = ProfileLoader(profiles_dir, store)
            await loader.scan()

            initial = await store.get_profile_registry("tpm")
            assert initial["description"] == "initial"

            # Stomp the file with malformed content.
            (profiles_dir / "tpm" / "profile.md").write_text(
                "---\nbroken: true\n---\nbody\n", encoding="utf-8"
            )
            results = await loader.scan()
            assert results == [("tpm", "errored")]

            # Existing registry row stays intact — we don't blow away the old
            # description just because the new file is broken.
            still = await store.get_profile_registry("tpm")
            assert still["description"] == "initial"
            await store.close()

        run(_t())
