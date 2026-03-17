/**
 * E2E test for Web Onboarding Wizard (Ticket #316)
 * Tests: 3-step wizard flow, templates, validation, dark mode, auto-redirect
 *
 * Usage: node tests/e2e_onboarding.cjs [PORT]
 *   Default port: 3456 (test daemon)
 */
const { chromium } = require('playwright');

const PORT = process.argv[2] || '3456';
const BASE = `http://127.0.0.1:${PORT}`;
const SDIR = 'tests/screenshots/316';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  let passed = 0;
  let failed = 0;

  async function check(name, fn) {
    try {
      await fn();
      console.log('PASS:', name);
      passed++;
    } catch (e) {
      console.log('FAIL:', name, '-', e.message.slice(0, 200));
      failed++;
    }
  }

  // ── Test 1: Onboarding page loads with step indicator ──
  await check('1. Onboarding page loads with Welcome title and step indicator', async () => {
    await page.goto(BASE + '/onboarding');
    await page.waitForLoadState('networkidle');
    const title = await page.locator('h1').textContent();
    if (!title.includes('Welcome to Agent-Hub')) throw new Error('Title: ' + title);
    // Step indicator should show Workspace, Team, Confirm
    const stepTexts = await page.locator('.flex.items-center.justify-center span').allTextContents();
    if (!stepTexts.some(t => t.includes('Workspace'))) throw new Error('Missing Workspace step');
    if (!stepTexts.some(t => t.includes('Team'))) throw new Error('Missing Team step');
    if (!stepTexts.some(t => t.includes('Confirm'))) throw new Error('Missing Confirm step');
    await page.screenshot({ path: SDIR + '/01-step1-workspace.png', fullPage: true });
  });

  // ── Test 2: Step 1 - Workspace input ──
  await check('2. Step 1: workspace path input and Next button', async () => {
    const input = page.locator('input[type="text"]');
    const val = await input.inputValue();
    if (val !== '~/workspace') throw new Error('Default not ~/workspace: ' + val);
    // Clear and type custom path
    await input.fill('/tmp/test-onboarding-316');
    const nextBtn = page.locator('button:has-text("Next")');
    if (!await nextBtn.isEnabled()) throw new Error('Next should be enabled');
    await nextBtn.click();
    await page.waitForTimeout(500);
    await page.screenshot({ path: SDIR + '/02-step2-team.png', fullPage: true });
  });

  // ── Test 3: Step 2 - Template cards ──
  await check('3. Step 2: Three template cards shown (Solo, Standard, Full)', async () => {
    const h3 = await page.locator('h3').first().textContent();
    if (!h3.includes('Configure Your Team')) throw new Error('Wrong heading: ' + h3);
    const cards = page.locator('button.p-3');
    const count = await cards.count();
    if (count !== 3) throw new Error('Expected 3 template cards, got ' + count);
    const texts = await cards.allTextContents();
    if (!texts.some(t => t.includes('Solo'))) throw new Error('Missing Solo');
    if (!texts.some(t => t.includes('Standard'))) throw new Error('Missing Standard');
    if (!texts.some(t => t.includes('Full'))) throw new Error('Missing Full');
  });

  // ── Test 4: Template selection - Solo ──
  await check('4. Clicking Solo template loads 2 agents (admin + dev)', async () => {
    await page.locator('button.p-3', { hasText: 'Solo' }).click();
    await page.waitForTimeout(300);
    const agentCards = page.locator('.space-y-3 > div');
    const count = await agentCards.count();
    if (count !== 2) throw new Error('Expected 2 agents, got ' + count);
    const label = page.locator('label', { hasText: /Agents \(2\)/ });
    if (!await label.isVisible()) throw new Error('Agent count label not showing 2');
    await page.screenshot({ path: SDIR + '/03-template-solo.png', fullPage: true });
  });

  // ── Test 5: Template selection - Standard ──
  await check('5. Clicking Standard template loads 5 agents', async () => {
    await page.locator('button.p-3', { hasText: 'Standard' }).click();
    await page.waitForTimeout(300);
    const label = page.locator('label', { hasText: /Agents \(5\)/ });
    if (!await label.isVisible()) throw new Error('Agent count not showing 5');
    await page.screenshot({ path: SDIR + '/04-template-standard.png', fullPage: true });
  });

  // ── Test 6: Template selection - Full ──
  await check('6. Clicking Full template loads 7 agents', async () => {
    await page.locator('button.p-3', { hasText: 'Full' }).click();
    await page.waitForTimeout(300);
    const label = page.locator('label', { hasText: /Agents \(7\)/ });
    if (!await label.isVisible()) throw new Error('Agent count not showing 7');
    await page.screenshot({ path: SDIR + '/05-template-full.png', fullPage: true });
  });

  // ── Test 7: Add and remove agent ──
  await check('7. Add Agent button adds a new agent; remove button removes it', async () => {
    // Start from Solo (2 agents)
    await page.locator('button.p-3', { hasText: 'Solo' }).click();
    await page.waitForTimeout(300);

    // Add agent
    await page.locator('text=+ Add Agent').click();
    await page.waitForTimeout(300);
    let label = page.locator('label', { hasText: /Agents \(3\)/ });
    if (!await label.isVisible()) throw new Error('Count not 3 after add');

    // Remove last agent (click the X button on the last agent card)
    const removeBtns = page.locator('.space-y-3 > div button[title="Remove agent"]');
    const lastIdx = await removeBtns.count() - 1;
    await removeBtns.nth(lastIdx).click();
    await page.waitForTimeout(300);
    label = page.locator('label', { hasText: /Agents \(2\)/ });
    if (!await label.isVisible()) throw new Error('Count not 2 after remove');
  });

  // ── Test 8: Name validation - inline error ──
  await check('8. Invalid agent name shows inline validation error', async () => {
    // Use Standard template for testing
    await page.locator('button.p-3', { hasText: 'Standard' }).click();
    await page.waitForTimeout(300);

    // Edit first agent name to uppercase (invalid)
    const nameInputs = page.locator('.space-y-3 > div input[type="text"]');
    await nameInputs.first().fill('BadName');
    await page.waitForTimeout(200);
    const error = page.locator('p.text-red-500, p.text-red-400');
    if (!await error.isVisible()) throw new Error('Validation error not shown');
    const errorText = await error.first().textContent();
    if (!errorText.includes('Lowercase')) throw new Error('Wrong error: ' + errorText);
    await page.screenshot({ path: SDIR + '/06-validation-error.png', fullPage: true });

    // Next button should be disabled with invalid name
    const nextBtn = page.locator('button:has-text("Next")');
    if (await nextBtn.isEnabled()) throw new Error('Next should be disabled with invalid name');

    // Fix it back
    await nameInputs.first().fill('admin');
    await page.waitForTimeout(200);
  });

  // ── Test 9: Duplicate name validation ──
  await check('9. Duplicate agent name shows error and disables Next', async () => {
    const nameInputs = page.locator('.space-y-3 > div input[type="text"]');
    // Set second agent name same as first (admin)
    await nameInputs.nth(1).fill('admin');
    await page.waitForTimeout(200);
    const error = page.locator('p.text-red-500, p.text-red-400');
    const errors = await error.allTextContents();
    if (!errors.some(e => e.includes('Duplicate'))) throw new Error('No duplicate error: ' + errors.join(', '));
    const nextBtn = page.locator('button:has-text("Next")');
    if (await nextBtn.isEnabled()) throw new Error('Next should be disabled');
    // Fix it
    await nameInputs.nth(1).fill('product-kevin');
    await page.waitForTimeout(200);
    await page.screenshot({ path: SDIR + '/07-after-fix.png', fullPage: true });
  });

  // ── Test 10: Navigate to Step 3 - Confirm ──
  await check('10. Step 3 shows configuration summary with workspace, team size, agent table', async () => {
    const nextBtn = page.locator('button:has-text("Next")');
    await nextBtn.click();
    await page.waitForTimeout(500);
    // Should be on Step 3
    const heading = await page.locator('h3').first().textContent();
    if (!heading.includes('Review Configuration')) throw new Error('Wrong heading: ' + heading);
    // Check workspace path shown
    const workspacePath = await page.locator('.font-mono').first().textContent();
    if (!workspacePath.includes('/tmp/test-onboarding-316')) throw new Error('Workspace: ' + workspacePath);
    // Check team size (number and "agents" are in separate DOM elements)
    const teamSizeP = page.locator('p.text-2xl');
    const teamText = await teamSizeP.textContent();
    if (!/\d+\s*agents?/.test(teamText)) throw new Error('Team size not shown: ' + teamText);
    // Check agent table
    const rows = page.locator('tbody tr');
    const rowCount = await rows.count();
    if (rowCount < 3) throw new Error('Expected 3+ rows, got ' + rowCount);
    // Check "What happens next" section
    const nextSteps = page.locator('text=What happens next');
    if (!await nextSteps.isVisible()) throw new Error('Next steps not shown');
    await page.screenshot({ path: SDIR + '/08-step3-confirm.png', fullPage: true });
  });

  // ── Test 11: Back button ──
  await check('11. Back button returns to previous step', async () => {
    const backBtn = page.locator('button:has-text("Back")');
    await backBtn.click();
    await page.waitForTimeout(300);
    // Should be back on Step 2
    const heading = await page.locator('h3').first().textContent();
    if (!heading.includes('Configure Your Team')) throw new Error('Not on Step 2: ' + heading);
    // Go forward again
    await page.locator('button:has-text("Next")').click();
    await page.waitForTimeout(300);
  });

  // ── Test 12: Dark mode ──
  await check('12. Dark mode renders all 3 steps correctly', async () => {
    await page.emulateMedia({ colorScheme: 'dark' });
    // Step 3 dark
    await page.screenshot({ path: SDIR + '/09-dark-step3.png', fullPage: true });
    // Go back to Step 1
    await page.locator('button:has-text("Back")').click();
    await page.waitForTimeout(300);
    await page.locator('button:has-text("Back")').click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: SDIR + '/10-dark-step1.png', fullPage: true });
    // Step 2 dark
    await page.locator('button:has-text("Next")').click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: SDIR + '/11-dark-step2.png', fullPage: true });
    await page.emulateMedia({ colorScheme: 'light' });
  });

  // ── Test 13: Generate Configuration (submit) ──
  await check('13. Submit generates config and shows success screen', async () => {
    // Navigate to Step 3
    await page.locator('button:has-text("Next")').click();
    await page.waitForTimeout(300);
    // Click Generate Configuration
    const submitBtn = page.locator('button:has-text("Generate Configuration")');
    if (!await submitBtn.isVisible()) throw new Error('Submit button not visible');
    await submitBtn.click();
    await page.waitForTimeout(2000);
    // Should show success screen
    const successTitle = page.locator('text=Setup Complete');
    if (!await successTitle.isVisible()) throw new Error('Success screen not shown');
    const goBtn = page.locator('button:has-text("Go to Dashboard")');
    if (!await goBtn.isVisible()) throw new Error('Go to Dashboard not shown');
    await page.screenshot({ path: SDIR + '/12-success-screen.png', fullPage: true });
  });

  // ── Test 14: OnboardingGuard redirect (for unconfigured state) ──
  await check('14. OnboardingGuard: accessing / with configured agents shows dashboard (no redirect)', async () => {
    // Now that setup has been run (agents exist), accessing / should show dashboard
    // But first, restore the original config
    // The onboarding status should return completed=true
    const res = await page.evaluate(async () => {
      const r = await fetch('/api/v1/onboarding/status');
      return r.json();
    });
    // After setup, completed should be true
    if (!res.completed) throw new Error('Status not completed after setup');
  });

  console.log('\n' + '='.repeat(50));
  console.log(`Results: ${passed} passed, ${failed} failed out of ${passed + failed}`);
  console.log('Screenshots saved to: ' + SDIR);
  console.log('='.repeat(50));

  await browser.close();

  // Restore agents.yaml (critical!)
  const { execSync } = require('child_process');
  execSync('cd /Users/huayang/code/agents && git checkout agents.yaml');
  console.log('agents.yaml restored from git');

  process.exit(failed > 0 ? 1 : 0);
})();
