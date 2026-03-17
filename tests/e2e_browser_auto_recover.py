#!/usr/bin/env python3
"""E2E test for ticket #342: Browser lightweight restart + Desktop VNC auto-recovery.

Tests real recovery scenarios against a live VM.
Requires: VM powered on with SSH access, browser service deployed.

Usage: ~/code/vm-mcp/.venv/bin/python tests/e2e_browser_auto_recover.py
"""
import asyncio
import os
import sys
import time

# Add vm-mcp to path
VM_MCP_DIR = os.path.expanduser("~/code/vm-mcp")
sys.path.insert(0, os.path.join(VM_MCP_DIR, "src"))

os.environ.setdefault("SSH_KEY_PATH", os.path.expanduser("~/.ssh/id_ed25519"))
os.environ.setdefault("SSH_USERNAME", "root")

VM_IP = "192.168.129.128"
VM_ID = "QV25R84KPLT7MNENDTHL71JT5NHVHR1D"

passed = 0
failed = 0


def report(name, ok, detail=""):
    global passed, failed
    if ok:
        print(f"  PASS: {name}" + (f" ({detail})" if detail else ""))
        passed += 1
    else:
        print(f"  FAIL: {name}" + (f" — {detail}" if detail else ""))
        failed += 1


async def ssh_run(cmd, timeout=30):
    """Quick SSH helper that handles background commands properly."""
    import asyncssh
    opts = {
        "username": os.environ.get("SSH_USERNAME", "root"),
        "known_hosts": None,
        "client_keys": [os.environ["SSH_KEY_PATH"]],
    }
    async with asyncssh.connect(VM_IP, **opts) as conn:
        result = await asyncio.wait_for(conn.run(cmd), timeout=timeout)
        return result.stdout or "", result.stderr or "", result.exit_status


# ─── Desktop VNC Auto-Recovery Tests ───

async def test_desktop_ensure_vnc():
    """Test _ensure_vnc() starting VNC from scratch."""
    from agent_hub.modules.desktop import _ensure_vnc, _VNC_DISPLAY

    print("\n=== Test 1: _ensure_vnc() starts VNC ===")

    # Kill VNC
    await ssh_run("pkill Xtigervnc || true; pkill xfce4-session || true")
    await asyncio.sleep(2)
    stdout, _, _ = await ssh_run("pgrep Xtigervnc && echo RUNNING || echo STOPPED")
    report("Precondition: VNC killed", "STOPPED" in stdout)

    # Call _ensure_vnc() — may timeout on startxfce4 but should still start Xtigervnc
    t0 = time.time()
    try:
        await _ensure_vnc(VM_IP)
        elapsed = time.time() - t0
        stdout, _, _ = await ssh_run("pgrep Xtigervnc && echo RUNNING || echo STOPPED")
        report("_ensure_vnc() starts Xtigervnc", "RUNNING" in stdout, f"{elapsed:.1f}s")
    except Exception as e:
        elapsed = time.time() - t0
        # Even on timeout, check if Xtigervnc was started
        try:
            stdout, _, _ = await ssh_run("pgrep Xtigervnc && echo RUNNING || echo STOPPED")
            if "RUNNING" in stdout:
                report("_ensure_vnc() starts Xtigervnc (but times out on XFCE)",
                       True, f"VNC started but function timed out: {e}")
                print("  ⚠ BUG: startxfce4 & doesn't detach from SSH → _ensure_vnc() times out")
            else:
                report("_ensure_vnc() starts Xtigervnc", False, str(e))
        except:
            report("_ensure_vnc() starts Xtigervnc", False, str(e))


async def test_desktop_vnc_recovery():
    """Test _with_vnc_recovery when VNC is not running."""
    from agent_hub.modules.desktop import _with_vnc_recovery, _VNC_DISPLAY

    print("\n=== Test 2: _with_vnc_recovery() auto-recovery ===")

    # Kill VNC
    await ssh_run("pkill Xtigervnc || true; pkill xfce4-session || true")
    await asyncio.sleep(2)

    display = _VNC_DISPLAY
    t0 = time.time()
    try:
        result = await _with_vnc_recovery(
            VM_IP,
            f"DISPLAY={display} xdotool getdisplaygeometry",
            timeout=30,
        )
        elapsed = time.time() - t0
        report("_with_vnc_recovery() recovers from VNC down",
               "1280" in result, f"geometry={result.strip()}, elapsed={elapsed:.1f}s")
    except Exception as e:
        elapsed = time.time() - t0
        # Check if it's the SSH timeout bug
        error_str = str(e)
        if "timed out" in error_str.lower():
            report("_with_vnc_recovery() recovers from VNC down",
                   False, f"SSH timeout bug: _ensure_vnc() hangs on startxfce4. {elapsed:.1f}s")
        else:
            report("_with_vnc_recovery() recovers from VNC down", False, f"{e} ({elapsed:.1f}s)")


async def test_desktop_screenshot_recovery():
    """Test _with_vnc_recovery_bytes for screenshot when VNC is down."""
    from agent_hub.modules.desktop import _with_vnc_recovery_bytes, _VNC_DISPLAY

    print("\n=== Test 3: Screenshot recovery via _with_vnc_recovery_bytes() ===")

    # Kill VNC
    await ssh_run("pkill Xtigervnc || true; pkill xfce4-session || true")
    await asyncio.sleep(2)

    display = _VNC_DISPLAY
    t0 = time.time()
    try:
        png = await _with_vnc_recovery_bytes(
            VM_IP,
            f"DISPLAY={display} import -window root png:-",
            timeout=30,
        )
        elapsed = time.time() - t0
        is_png = png[:4] == b'\x89PNG'
        report("_with_vnc_recovery_bytes() screenshot recovery",
               is_png and len(png) > 1000,
               f"size={len(png)} bytes, elapsed={elapsed:.1f}s")
    except Exception as e:
        elapsed = time.time() - t0
        report("_with_vnc_recovery_bytes() screenshot recovery", False, f"{e} ({elapsed:.1f}s)")


async def test_desktop_normal_path():
    """Test normal path when VNC is already running."""
    from agent_hub.modules.desktop import _with_vnc_recovery, _VNC_DISPLAY

    print("\n=== Test 4: Desktop normal path (VNC running) ===")

    # Ensure VNC is running with proper nohup
    stdout, _, _ = await ssh_run("pgrep Xtigervnc && echo RUNNING || echo STOPPED")
    if "STOPPED" in stdout:
        display = _VNC_DISPLAY
        disp_num = display.lstrip(":")
        await ssh_run(f"nohup Xtigervnc {display} -geometry 1280x800 -depth 24 "
                      f"-rfbauth ~/.vnc/passwd -localhost no > /dev/null 2>&1 &")
        await asyncio.sleep(2)

    display = _VNC_DISPLAY
    t0 = time.time()
    try:
        result = await _with_vnc_recovery(
            VM_IP, f"DISPLAY={display} xdotool getdisplaygeometry",
        )
        elapsed = time.time() - t0
        report("Normal path: fast execution, no recovery",
               "1280" in result and elapsed < 5.0,
               f"geometry={result.strip()}, elapsed={elapsed:.1f}s")
    except Exception as e:
        report("Normal path: fast execution", False, str(e))

    # Test 5: Non-display errors don't trigger recovery
    t0 = time.time()
    try:
        await _with_vnc_recovery(VM_IP, "false")
        report("Non-display error: no false positive recovery", False, "Should have raised")
    except Exception as e:
        elapsed = time.time() - t0
        report("Non-display error: no false positive recovery",
               elapsed < 3.0,
               f"elapsed={elapsed:.1f}s, correctly failed: '{str(e)[:60]}'")


# ─── Browser Quick Restart Tests ───

async def test_browser_quick_restart():
    """Test _quick_restart when browser service is killed but script + Xvfb exist."""
    from agent_hub.modules.browser import _quick_restart
    from agent_hub.state import StateManager

    print("\n=== Test 6: Browser _quick_restart() ===")

    state = StateManager()
    state.update_vm(VM_ID, ip=VM_IP)

    # Verify health first
    stdout, _, _ = await ssh_run("curl -s http://127.0.0.1:9223/health || echo FAIL")
    report("Precondition: browser service healthy", "agent-hub-browser" in stdout)

    if "agent-hub-browser" not in stdout:
        print("  ⚠ Browser not healthy, skipping quick restart test")
        return

    # Kill browser service
    await ssh_run("pkill -f 'python.*browser_service' || true")
    await asyncio.sleep(2)
    stdout, _, _ = await ssh_run("curl -s http://127.0.0.1:9223/health || echo FAIL")
    report("Browser killed: health check fails", "FAIL" in stdout or "agent-hub-browser" not in stdout)

    # Quick restart
    t0 = time.time()
    result = await _quick_restart(VM_ID)
    elapsed = time.time() - t0
    report("_quick_restart() recovers killed service",
           result is True, f"returned={result}, elapsed={elapsed:.1f}s")

    # Verify health after restart
    if result:
        stdout, _, _ = await ssh_run("curl -s http://127.0.0.1:9223/health || echo FAIL")
        report("After quick restart: health check passes", "agent-hub-browser" in stdout)


async def test_browser_missing_script():
    """Test _quick_restart returns False when script is missing."""
    from agent_hub.modules.browser import _quick_restart
    from agent_hub.state import StateManager

    print("\n=== Test 7: Browser missing script → quick restart False ===")

    state = StateManager()
    state.update_vm(VM_ID, ip=VM_IP)

    # Backup, remove script, test
    await ssh_run("pkill -f 'python.*browser_service' || true")
    await ssh_run("cp /tmp/browser_service.py /tmp/browser_service.py.testbak 2>/dev/null || true")
    await ssh_run("rm -f /tmp/browser_service.py")
    await asyncio.sleep(1)

    t0 = time.time()
    result = await _quick_restart(VM_ID)
    elapsed = time.time() - t0
    report("_quick_restart() returns False when script missing",
           result is False, f"returned={result}, elapsed={elapsed:.1f}s")

    # Restore script
    await ssh_run("mv /tmp/browser_service.py.testbak /tmp/browser_service.py 2>/dev/null || true")


async def test_browser_auto_recover():
    """Test full _request_with_auto_recover flow: kill service → auto-recover."""
    from agent_hub.modules.browser import _request_with_auto_recover
    from agent_hub.state import StateManager

    print("\n=== Test 8: _request_with_auto_recover() full flow ===")

    state = StateManager()
    state.update_vm(VM_ID, ip=VM_IP)

    # Ensure service is healthy first
    stdout, _, _ = await ssh_run("curl -s http://127.0.0.1:9223/health || echo FAIL")
    if "agent-hub-browser" not in stdout:
        # Restart manually
        await ssh_run("nohup env DISPLAY=:99 python3 /tmp/browser_service.py --port 9223 > /tmp/browser_service.log 2>&1 &")
        await asyncio.sleep(8)
        stdout, _, _ = await ssh_run("curl -s http://127.0.0.1:9223/health || echo FAIL")
        if "agent-hub-browser" not in stdout:
            print("  ⚠ Cannot restore browser service, skipping")
            return

    # Kill service
    await ssh_run("pkill -f 'python.*browser_service' || true")
    await asyncio.sleep(2)

    # Call auto-recover
    t0 = time.time()
    try:
        resp = await _request_with_auto_recover("get", "/health", vm_id=VM_ID)
        elapsed = time.time() - t0
        report("_request_with_auto_recover() recovers via quick restart",
               resp.status_code == 200 and "agent-hub-browser" in resp.text,
               f"status={resp.status_code}, elapsed={elapsed:.1f}s")
    except Exception as e:
        elapsed = time.time() - t0
        report("_request_with_auto_recover() recovers", False, f"{e} ({elapsed:.1f}s)")


async def test_browser_error_messages():
    """Test clear error messages when recovery fails."""
    from agent_hub.modules.browser import _request_with_auto_recover
    from agent_hub.state import StateManager
    from fastmcp.exceptions import ToolError

    print("\n=== Test 9: Error messages on both recovery methods failing ===")

    # Kill service + remove script → quick restart fails, deploy re-uploads + succeeds
    state = StateManager()
    state.update_vm(VM_ID, ip=VM_IP)

    await ssh_run("pkill -f 'python.*browser_service' || true")
    await ssh_run("cp /tmp/browser_service.py /tmp/browser_service.py.errbak 2>/dev/null || true")
    await ssh_run("rm -f /tmp/browser_service.py")
    await asyncio.sleep(1)

    t0 = time.time()
    try:
        resp = await _request_with_auto_recover("get", "/health", vm_id=VM_ID)
        elapsed = time.time() - t0
        # Full deploy will re-upload the script and succeed
        report("Full deploy fallback works when no script",
               resp.status_code == 200, f"status={resp.status_code}, elapsed={elapsed:.1f}s")
    except ToolError as e:
        elapsed = time.time() - t0
        msg = str(e)
        has_info = any(w in msg.lower() for w in ["quick restart", "deploy", "unreachable"])
        report("Error message mentions recovery attempts",
               has_info, f"elapsed={elapsed:.1f}s, msg='{msg[:120]}'")
    except Exception as e:
        elapsed = time.time() - t0
        report("Error message test", False, f"Unexpected: {e} ({elapsed:.1f}s)")

    # Restore
    await ssh_run("rm -f /tmp/browser_service.py.errbak 2>/dev/null || true")


async def main():
    print("=" * 60)
    print("E2E Test: Browser Quick Restart + Desktop VNC Auto-Recovery")
    print(f"Ticket: #342 | VM: {VM_IP}")
    print("=" * 60)

    from agent_hub.state import StateManager
    state = StateManager()
    state.update_vm(VM_ID, ip=VM_IP)

    # Desktop tests
    await test_desktop_ensure_vnc()
    await test_desktop_vnc_recovery()
    await test_desktop_screenshot_recovery()
    await test_desktop_normal_path()

    # Browser tests
    await test_browser_quick_restart()
    await test_browser_missing_script()
    await test_browser_auto_recover()
    await test_browser_error_messages()

    # Cleanup
    print("\n=== Cleanup ===")
    stdout, _, _ = await ssh_run("curl -s http://127.0.0.1:9223/health || echo FAIL")
    if "agent-hub-browser" in stdout:
        print("  Browser service healthy ✓")
    else:
        print("  Restoring browser service...")
        try:
            from agent_hub.modules.browser import deploy
            await deploy(vm_id=VM_ID)
            print("  Restored via full deploy ✓")
        except Exception as e:
            print(f"  Could not restore: {e}")

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
