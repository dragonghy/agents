/**
 * E2E Test: SEOPilot Lite Popup UI Rendering
 *
 * Since the popup can't run chrome.tabs.query in automated tests,
 * this script renders the popup HTML with injected analysis data
 * to capture visual screenshots of the complete UI.
 */

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const DIST_PATH = path.resolve(__dirname, '../projects/seopilot-chrome-ext/dist');
const SCREENSHOTS_DIR = path.resolve(__dirname, 'screenshots');

async function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

async function main() {
  // Read the popup HTML and CSS
  const popupHtml = fs.readFileSync(path.join(DIST_PATH, 'popup.html'), 'utf8');
  const popupCss = fs.readFileSync(path.join(DIST_PATH, 'popup.css'), 'utf8');

  // Create a self-contained HTML page with inlined CSS (no external deps)
  const standaloneHtml = popupHtml
    .replace('<link rel="stylesheet" href="popup.css" />', `<style>${popupCss}</style>`)
    .replace('<script src="popup.js"></script>', ''); // Remove the popup.js (we'll inject data manually)

  const browser = await chromium.launch({ headless: true });

  // Mock analysis result (well-optimized page)
  const goodResult = {
    url: "https://example.com/best-coffee-shops-sf",
    title: "Best Coffee Shops in San Francisco",
    overallScore: 92,
    scoreColor: "green",
    checks: [
      { id: "meta-title", name: "Meta Title", status: "pass", score: 100, weight: 20, issues: [], details: { title: "Best Coffee Shops in San Francisco - A Local Guide", length: 50 } },
      { id: "meta-description", name: "Meta Description", status: "pass", score: 100, weight: 20, issues: [], details: { description: "Discover the top 15 coffee shops in San Francisco, from artisan roasters to cozy neighborhood cafes.", length: 142 } },
      { id: "headings", name: "Heading Structure", status: "pass", score: 100, weight: 15, issues: [], details: { counts: { h1: 1, h2: 3, h3: 2 }, h1Text: "Best Coffee Shops in SF" } },
      { id: "image-alt", name: "Image Alt Text", status: "pass", score: 100, weight: 15, issues: [], details: { totalImages: 5, withAlt: 5, withoutAlt: 0, lowQualityAlt: 0 } },
      { id: "links", name: "Link Analysis", status: "pass", score: 100, weight: 15, issues: [], details: { totalLinks: 12, internalLinks: 8, externalLinks: 4, nofollowLinks: 0, emptyLinks: 0 } },
      { id: "social-meta", name: "OG / Twitter Card", status: "warning", score: 56, weight: 15, issues: [
        { ruleId: "twitter-card-incomplete", severity: "info", message: "Twitter Card tags incomplete. Missing: twitter:description, twitter:image.", currentValue: "2/4 present", recommendation: "Add the missing Twitter Card tags: twitter:description, twitter:image." }
      ], details: { og: { title: "Best Coffee Shops", description: "Top 15 SF cafes", image: "https://example.com/coffee.jpg", type: "article", url: "https://example.com/best-coffee-shops-sf" }, twitter: { card: "summary", title: "Best Coffee Shops in SF", description: null, image: null }, ogFieldsPresent: 5, twFieldsPresent: 2 } }
    ],
    timestamp: Date.now()
  };

  // Mock analysis result (poorly optimized page)
  const badResult = {
    url: "https://example.com/page1",
    title: "Home",
    overallScore: 22,
    scoreColor: "red",
    checks: [
      { id: "meta-title", name: "Meta Title", status: "fail", score: 40, weight: 20, issues: [
        { ruleId: "meta-title-short", severity: "warning", message: "Title is too short (4 chars). Aim for 30-60 characters.", currentValue: 4, recommendation: "Expand the title to include more descriptive keywords (30-60 chars)." },
        { ruleId: "meta-title-generic", severity: "warning", message: 'Title appears generic ("Home"). Use a unique, descriptive title.', currentValue: "Home", recommendation: "Replace with a title that describes the page content and includes target keywords." }
      ], details: { title: "Home", length: 4 } },
      { id: "meta-description", name: "Meta Description", status: "fail", score: 0, weight: 20, issues: [
        { ruleId: "meta-desc-missing", severity: "critical", message: "Meta description is missing. Search engines use this in results snippets.", recommendation: "Add a <meta name='description'> tag with a compelling description (120-160 characters)." }
      ], details: { description: "", length: 0 } },
      { id: "headings", name: "Heading Structure", status: "fail", score: 30, weight: 15, issues: [
        { ruleId: "heading-no-h1", severity: "critical", message: "No H1 tag found. Every page should have exactly one H1.", currentValue: 0, recommendation: "Add a single H1 tag that describes the main topic of the page." }
      ], details: { counts: { h1: 0, h2: 1 }, h1Text: null } },
      { id: "image-alt", name: "Image Alt Text", status: "fail", score: 0, weight: 15, issues: [
        { ruleId: "image-alt-missing", severity: "critical", message: "3 of 3 image(s) missing alt text.", currentValue: "3/3 missing", recommendation: "Add descriptive alt text to all images for accessibility and SEO." }
      ], details: { totalImages: 3, withAlt: 0, withoutAlt: 3, lowQualityAlt: 0 } },
      { id: "links", name: "Link Analysis", status: "warning", score: 50, weight: 15, issues: [
        { ruleId: "links-none", severity: "warning", message: "No links found on the page. Internal linking helps SEO.", currentValue: 0, recommendation: "Add internal links to relevant pages and external links to authoritative sources." }
      ], details: { totalLinks: 0, internalLinks: 0, externalLinks: 0, nofollowLinks: 0, emptyLinks: 0 } },
      { id: "social-meta", name: "OG / Twitter Card", status: "fail", score: 0, weight: 15, issues: [
        { ruleId: "social-meta-missing", severity: "critical", message: "No Open Graph or Twitter Card meta tags found. Social sharing will use fallback data.", recommendation: "Add og:title, og:description, og:image and twitter:card tags for better social media previews." }
      ], details: { og: {}, twitter: {}, ogFieldsPresent: 0, twFieldsPresent: 0 } }
    ],
    timestamp: Date.now()
  };

  // Script to inject analysis results into the popup DOM
  const renderScript = (result) => `
    (function() {
      const result = ${JSON.stringify(result)};

      // Hide loading, show results
      document.getElementById('loading').classList.add('hidden');
      document.getElementById('error').classList.add('hidden');
      document.getElementById('results').classList.remove('hidden');

      // Page info
      const pageInfoEl = document.getElementById('page-info');
      pageInfoEl.textContent = result.url;
      pageInfoEl.title = result.url;

      // Score ring
      const scoreValueEl = document.getElementById('score-value');
      const scoreLabelEl = document.getElementById('score-label');
      const scoreCircleEl = document.getElementById('score-circle');

      scoreValueEl.textContent = String(result.overallScore);

      const colorMap = { red: '#ef4444', yellow: '#f59e0b', green: '#22c55e' };
      scoreCircleEl.style.stroke = colorMap[result.scoreColor] || colorMap.red;

      const circumference = 2 * Math.PI * 52;
      const offset = circumference - (result.overallScore / 100) * circumference;
      scoreCircleEl.style.strokeDashoffset = String(offset);

      const labels = { green: 'Good', yellow: 'Needs Work', red: 'Poor' };
      scoreLabelEl.textContent = 'SEO Score — ' + (labels[result.scoreColor] || '');

      // Checks
      const checksListEl = document.getElementById('checks-list');
      checksListEl.innerHTML = '';

      const statusIcons = { pass: '\\u2713', warning: '!', fail: '\\u2717' };
      const statusColors = { pass: '#22c55e', warning: '#f59e0b', fail: '#ef4444' };

      for (const check of result.checks) {
        const item = document.createElement('div');
        item.className = 'check-item';

        let issuesHtml = '';
        if (check.issues.length === 0) {
          issuesHtml = '<div class="check-pass-msg">\\u2713 All checks passed</div>';
        } else {
          for (const issue of check.issues) {
            issuesHtml += '<div class="issue-item"><span class="issue-badge ' + issue.severity + '">' + issue.severity + '</span><div class="issue-content"><div class="issue-message">' + issue.message + '</div><div class="issue-recommendation">' + issue.recommendation + '</div></div></div>';
          }
        }

        item.innerHTML =
          '<div class="check-header" onclick="this.parentElement.classList.toggle(\\'expanded\\')">' +
          '  <div class="check-name">' +
          '    <div class="check-status-icon ' + check.status + '">' + statusIcons[check.status] + '</div>' +
          '    <span>' + check.name + '</span>' +
          '  </div>' +
          '  <span class="check-score" style="color: ' + statusColors[check.status] + '">' + check.score + '/100</span>' +
          '  <span class="check-arrow">\\u25b6</span>' +
          '</div>' +
          '<div class="check-details">' + issuesHtml + '</div>';

        checksListEl.appendChild(item);
      }

      // Social previews
      const socialCheck = result.checks.find(c => c.id === 'social-meta');
      const titleCheck = result.checks.find(c => c.id === 'meta-title');
      const descCheck = result.checks.find(c => c.id === 'meta-description');

      const og = (socialCheck?.details?.og || {});
      const tw = (socialCheck?.details?.twitter || {});
      const pageTitle = titleCheck?.details?.title || result.title;
      const pageDesc = descCheck?.details?.description || '';

      let hostname = '';
      try { hostname = new URL(result.url).hostname; } catch { hostname = result.url; }

      const effectiveTitle = og.title || tw.title || pageTitle || '(No title)';
      const effectiveDesc = og.description || tw.description || pageDesc || '(No description)';

      document.getElementById('serp-url').textContent = result.url;
      document.getElementById('serp-title').textContent = effectiveTitle;
      document.getElementById('serp-desc').textContent = effectiveDesc;

      document.getElementById('tw-title').textContent = tw.title || effectiveTitle;
      document.getElementById('tw-desc').textContent = tw.description || effectiveDesc;
      document.getElementById('tw-domain').textContent = hostname;
      document.getElementById('tw-image').textContent = 'No image available';

      document.getElementById('fb-domain').textContent = hostname.toUpperCase();
      document.getElementById('fb-title').textContent = og.title || effectiveTitle;
      document.getElementById('fb-desc').textContent = og.description || effectiveDesc;
      document.getElementById('fb-image').textContent = 'No image available';

      if (og.image) {
        document.getElementById('fb-image').innerHTML = '<img src="' + og.image + '" alt="Preview" onerror="this.parentElement.textContent=\\'No image available\\'">';
        document.getElementById('tw-image').innerHTML = '<img src="' + (tw.image || og.image) + '" alt="Preview" onerror="this.parentElement.textContent=\\'No image available\\'">';
      }
    })();
  `;

  // =====================================================================
  // Screenshot 1: Good page - Analysis tab (light mode)
  // =====================================================================
  console.log('--- Rendering: Good page, Analysis tab (light mode) ---');
  const page1 = await browser.newPage();
  await page1.setViewportSize({ width: 400, height: 600 });
  await page1.setContent(standaloneHtml);
  await page1.evaluate(renderScript(goodResult));
  await sleep(300);
  await page1.screenshot({ path: path.join(SCREENSHOTS_DIR, 'seopilot-m2-good-analysis.png'), fullPage: true });
  console.log('Screenshot: seopilot-m2-good-analysis.png');

  // Expand first check to show details
  await page1.locator('.check-header').first().click();
  await sleep(200);
  await page1.screenshot({ path: path.join(SCREENSHOTS_DIR, 'seopilot-m2-good-expanded.png'), fullPage: true });
  console.log('Screenshot: seopilot-m2-good-expanded.png');

  // =====================================================================
  // Screenshot 2: Good page - Preview tab (social previews)
  // =====================================================================
  console.log('--- Rendering: Good page, Preview tab ---');
  await page1.locator('.tab[data-tab="preview"]').click();
  await sleep(300);
  await page1.screenshot({ path: path.join(SCREENSHOTS_DIR, 'seopilot-m2-good-preview.png'), fullPage: true });
  console.log('Screenshot: seopilot-m2-good-preview.png');

  // =====================================================================
  // Screenshot 3: Bad page - Analysis tab (light mode)
  // =====================================================================
  console.log('--- Rendering: Bad page, Analysis tab (light mode) ---');
  const page2 = await browser.newPage();
  await page2.setViewportSize({ width: 400, height: 600 });
  await page2.setContent(standaloneHtml);
  await page2.evaluate(renderScript(badResult));
  await sleep(300);
  await page2.screenshot({ path: path.join(SCREENSHOTS_DIR, 'seopilot-m2-bad-analysis.png'), fullPage: true });
  console.log('Screenshot: seopilot-m2-bad-analysis.png');

  // Expand all checks to show issues
  const checkHeaders = await page2.locator('.check-header').all();
  for (const header of checkHeaders) {
    await header.click();
    await sleep(100);
  }
  await page2.screenshot({ path: path.join(SCREENSHOTS_DIR, 'seopilot-m2-bad-expanded.png'), fullPage: true });
  console.log('Screenshot: seopilot-m2-bad-expanded.png');

  // =====================================================================
  // Screenshot 4: Good page - Dark mode
  // =====================================================================
  console.log('--- Rendering: Good page, Dark mode ---');
  const page3 = await browser.newPage();
  await page3.setViewportSize({ width: 400, height: 600 });
  await page3.emulateMedia({ colorScheme: 'dark' });
  await page3.setContent(standaloneHtml);
  await page3.evaluate(renderScript(goodResult));
  await sleep(300);
  await page3.screenshot({ path: path.join(SCREENSHOTS_DIR, 'seopilot-m2-dark-analysis.png'), fullPage: true });
  console.log('Screenshot: seopilot-m2-dark-analysis.png');

  // Dark mode preview tab
  await page3.locator('.tab[data-tab="preview"]').click();
  await sleep(300);
  await page3.screenshot({ path: path.join(SCREENSHOTS_DIR, 'seopilot-m2-dark-preview.png'), fullPage: true });
  console.log('Screenshot: seopilot-m2-dark-preview.png');

  // =====================================================================
  // Screenshot 5: Bad page - Dark mode
  // =====================================================================
  console.log('--- Rendering: Bad page, Dark mode ---');
  const page4 = await browser.newPage();
  await page4.setViewportSize({ width: 400, height: 600 });
  await page4.emulateMedia({ colorScheme: 'dark' });
  await page4.setContent(standaloneHtml);
  await page4.evaluate(renderScript(badResult));
  await sleep(300);

  // Expand all checks
  const badDarkHeaders = await page4.locator('.check-header').all();
  for (const header of badDarkHeaders) {
    await header.click();
    await sleep(100);
  }
  await page4.screenshot({ path: path.join(SCREENSHOTS_DIR, 'seopilot-m2-dark-bad.png'), fullPage: true });
  console.log('Screenshot: seopilot-m2-dark-bad.png');

  // =====================================================================
  // Screenshot 6: Settings panel
  // =====================================================================
  console.log('--- Rendering: Settings panel ---');
  const page5 = await browser.newPage();
  await page5.setViewportSize({ width: 400, height: 600 });
  await page5.setContent(standaloneHtml);
  // Show settings
  await page5.evaluate(() => {
    document.getElementById('loading').classList.add('hidden');
    document.getElementById('settings-panel').classList.remove('hidden');
  });
  await sleep(200);
  await page5.screenshot({ path: path.join(SCREENSHOTS_DIR, 'seopilot-m2-settings.png') });
  console.log('Screenshot: seopilot-m2-settings.png');

  // Settings with some unchecked
  await page5.locator('input[data-check="headings"]').uncheck();
  await page5.locator('input[data-check="links"]').uncheck();
  await sleep(200);
  await page5.screenshot({ path: path.join(SCREENSHOTS_DIR, 'seopilot-m2-settings-partial.png') });
  console.log('Screenshot: seopilot-m2-settings-partial.png');

  await browser.close();
  console.log('\n✓ All popup render screenshots captured');
}

main().catch(console.error);
