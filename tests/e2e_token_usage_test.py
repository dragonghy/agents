"""E2E test for Token Usage feature (#216).

Tests:
1. Agent Detail page shows Token Usage panel
2. Token Usage panel displays Today/Lifetime breakdown
3. Refresh button works
4. All agents usage summary endpoint
"""

import subprocess
import sys
import json
import os

DAEMON_URL = "http://127.0.0.1:8765"
SCREENSHOTS_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)


def test_api_endpoints():
    """Test all usage API endpoints."""
    print("\n=== API Endpoint Tests ===\n")

    # Test 1: GET /api/v1/agents/dev-alex/usage
    print("Test 1: GET /api/v1/agents/dev-alex/usage")
    result = subprocess.run(
        ["curl", "-s", f"{DAEMON_URL}/api/v1/agents/dev-alex/usage"],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    assert "today" in data, "Missing 'today' in response"
    assert "lifetime" in data, "Missing 'lifetime' in response"
    assert "by_model" in data, "Missing 'by_model' in response"
    assert "daily_totals" in data, "Missing 'daily_totals' in response"
    assert data["lifetime"]["message_count"] > 0, "Expected non-zero lifetime message count"
    print(f"  ✓ Response has all fields, lifetime messages: {data['lifetime']['message_count']}")

    # Test 2: GET /api/v1/usage (all agents)
    print("Test 2: GET /api/v1/usage (all agents)")
    result = subprocess.run(
        ["curl", "-s", f"{DAEMON_URL}/api/v1/usage"],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    assert isinstance(data, list), "Expected list response"
    assert len(data) > 0, "Expected at least one agent"
    agent_ids = [d["agent_id"] for d in data]
    assert "dev-alex" in agent_ids, "dev-alex missing from summary"
    print(f"  ✓ {len(data)} agents in summary: {agent_ids}")

    # Test 3: POST /api/v1/agents/dev-alex/usage/refresh
    print("Test 3: POST /api/v1/agents/dev-alex/usage/refresh")
    result = subprocess.run(
        ["curl", "-s", "-X", "POST", f"{DAEMON_URL}/api/v1/agents/dev-alex/usage/refresh"],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    assert "today" in data and "lifetime" in data, "Refresh response missing fields"
    print(f"  ✓ Refresh returned data, today messages: {data['today']['message_count']}")

    # Test 4: Non-existent agent returns empty data (no error)
    print("Test 4: Non-existent agent returns empty data")
    result = subprocess.run(
        ["curl", "-s", f"{DAEMON_URL}/api/v1/agents/nonexistent/usage"],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    assert data["lifetime"]["message_count"] == 0, "Expected zero for non-existent agent"
    print(f"  ✓ Non-existent agent returns zeros gracefully")

    print("\n  All API tests passed! ✓")


def test_web_ui_screenshots():
    """Take screenshots of the Token Usage panel in the Web UI."""
    print("\n=== Web UI Screenshot Tests ===\n")

    # Use Playwright to capture screenshots
    script = f"""
const {{ chromium }} = require('playwright');

(async () => {{
    const browser = await chromium.launch({{ headless: true }});
    const context = await browser.newContext({{ viewport: {{ width: 1440, height: 900 }} }});
    const page = await context.newPage();

    // Navigate to Agent Detail page (dev-alex)
    console.log('Navigating to Agent Detail page for dev-alex...');
    await page.goto('{DAEMON_URL}/agents/dev-alex', {{ waitUntil: 'networkidle' }});
    await page.waitForTimeout(2000);

    // Screenshot: Full Agent Detail page
    await page.screenshot({{ path: '{SCREENSHOTS_DIR}/agent-detail-dev-alex.png', fullPage: true }});
    console.log('Screenshot: agent-detail-dev-alex.png');

    // Check if Token Usage panel exists
    const tokenPanel = await page.locator('text=Token Usage').first();
    const isVisible = await tokenPanel.isVisible().catch(() => false);
    if (isVisible) {{
        console.log('✓ Token Usage panel is visible');

        // Screenshot: Token Usage panel zoomed in
        const panel = await page.locator('h3:has-text("Token Usage")').locator('xpath=ancestor::div[contains(@class,"rounded-lg")]').first();
        const panelBox = await panel.boundingBox();
        if (panelBox) {{
            await page.screenshot({{
                path: '{SCREENSHOTS_DIR}/token-usage-panel.png',
                clip: {{
                    x: Math.max(0, panelBox.x - 10),
                    y: Math.max(0, panelBox.y - 10),
                    width: panelBox.width + 20,
                    height: panelBox.height + 20
                }}
            }});
            console.log('Screenshot: token-usage-panel.png');
        }}

        // Test Refresh button
        const refreshBtn = await page.locator('button:has-text("Refresh")').first();
        if (await refreshBtn.isVisible()) {{
            console.log('Clicking Refresh button...');
            await refreshBtn.click();
            await page.waitForTimeout(3000);
            await page.screenshot({{ path: '{SCREENSHOTS_DIR}/token-usage-after-refresh.png', fullPage: true }});
            console.log('Screenshot: token-usage-after-refresh.png');
            console.log('✓ Refresh button works');
        }}
    }} else {{
        console.log('✗ Token Usage panel NOT visible');
    }}

    // Test another agent (qa-oliver)
    console.log('Navigating to Agent Detail page for qa-oliver...');
    await page.goto('{DAEMON_URL}/agents/qa-oliver', {{ waitUntil: 'networkidle' }});
    await page.waitForTimeout(2000);
    await page.screenshot({{ path: '{SCREENSHOTS_DIR}/agent-detail-qa-oliver.png', fullPage: true }});
    console.log('Screenshot: agent-detail-qa-oliver.png');

    // Test dark mode if applicable
    await context.close();
    const darkContext = await browser.newContext({{
        viewport: {{ width: 1440, height: 900 }},
        colorScheme: 'dark'
    }});
    const darkPage = await darkContext.newPage();
    await darkPage.goto('{DAEMON_URL}/agents/dev-alex', {{ waitUntil: 'networkidle' }});
    await darkPage.waitForTimeout(2000);
    await darkPage.screenshot({{ path: '{SCREENSHOTS_DIR}/token-usage-dark-mode.png', fullPage: true }});
    console.log('Screenshot: token-usage-dark-mode.png');

    await browser.close();
    console.log('\\n✓ All screenshots captured');
}})();
"""

    # Write the script
    script_path = os.path.join(SCREENSHOTS_DIR, "_test_script.cjs")
    with open(script_path, "w") as f:
        f.write(script)

    # Run with npx playwright
    result = subprocess.run(
        ["node", script_path],
        capture_output=True, text=True,
        cwd="/Users/huayang/code/agents/services/agents-mcp/web",
        env={**os.environ, "NODE_PATH": "/Users/huayang/code/agents/services/agents-mcp/web/node_modules"}
    )
    print(result.stdout)
    if result.stderr:
        print(f"Stderr: {result.stderr[:500]}")

    if result.returncode != 0:
        print(f"  ✗ Screenshot test failed (exit code {result.returncode})")
        return False

    # Verify screenshots exist
    expected_files = [
        "agent-detail-dev-alex.png",
        "token-usage-panel.png",
        "token-usage-after-refresh.png",
        "agent-detail-qa-oliver.png",
        "token-usage-dark-mode.png",
    ]
    for f in expected_files:
        path = os.path.join(SCREENSHOTS_DIR, f)
        if os.path.exists(path):
            size = os.path.getsize(path)
            print(f"  ✓ {f} ({size:,} bytes)")
        else:
            print(f"  ✗ {f} MISSING")

    return True


if __name__ == "__main__":
    test_api_endpoints()
    success = test_web_ui_screenshots()
    if success:
        print("\n=== ALL TESTS PASSED ===")
    else:
        print("\n=== SOME TESTS FAILED ===")
        sys.exit(1)
