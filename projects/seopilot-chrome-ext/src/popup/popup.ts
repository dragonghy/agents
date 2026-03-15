/**
 * Popup Script — Controls the popup UI and triggers analysis.
 *
 * M1: Core analysis + score display + check details
 * M2: Tab navigation, social previews, clipboard export, settings
 */

import type { AnalysisResult, CheckResult } from "../content/seo-checks";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface UserSettings {
  enabledChecks: Record<string, boolean>;
}

const DEFAULT_SETTINGS: UserSettings = {
  enabledChecks: {
    "meta-title": true,
    "meta-description": true,
    headings: true,
    "image-alt": true,
    links: true,
    "social-meta": true,
  },
};

// ---------------------------------------------------------------------------
// DOM References
// ---------------------------------------------------------------------------

const loadingEl = document.getElementById("loading")!;
const errorEl = document.getElementById("error")!;
const errorMessage = document.getElementById("error-message")!;
const retryBtn = document.getElementById("retry-btn")!;
const resultsEl = document.getElementById("results")!;
const pageInfoEl = document.getElementById("page-info")!;
const scoreValueEl = document.getElementById("score-value")!;
const scoreLabelEl = document.getElementById("score-label")!;
const scoreCircleEl = document.getElementById("score-circle")!;
const checksListEl = document.getElementById("checks-list")!;
const toastEl = document.getElementById("toast")!;

// Header buttons
const copyBtn = document.getElementById("copy-btn")!;
const settingsBtn = document.getElementById("settings-btn")!;

// Tabs
const tabButtons = document.querySelectorAll<HTMLButtonElement>(".tab");
const tabContents = document.querySelectorAll<HTMLElement>(".tab-content");

// Preview elements
const serpTitle = document.getElementById("serp-title")!;
const serpUrl = document.getElementById("serp-url")!;
const serpDesc = document.getElementById("serp-desc")!;
const twImage = document.getElementById("tw-image")!;
const twTitle = document.getElementById("tw-title")!;
const twDesc = document.getElementById("tw-desc")!;
const twDomain = document.getElementById("tw-domain")!;
const fbImage = document.getElementById("fb-image")!;
const fbTitle = document.getElementById("fb-title")!;
const fbDesc = document.getElementById("fb-desc")!;
const fbDomain = document.getElementById("fb-domain")!;

// Settings
const settingsPanel = document.getElementById("settings-panel")!;
const settingsClose = document.getElementById("settings-close")!;
const settingsSave = document.getElementById("settings-save")!;
const settingsChecks = document.getElementById("settings-checks")!;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let currentResult: AnalysisResult | null = null;
let userSettings: UserSettings = { ...DEFAULT_SETTINGS };

// ---------------------------------------------------------------------------
// Main Entry
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  await loadSettings();
  runAnalysis();

  retryBtn.addEventListener("click", runAnalysis);
  copyBtn.addEventListener("click", copyToClipboard);
  settingsBtn.addEventListener("click", openSettings);
  settingsClose.addEventListener("click", closeSettings);
  settingsSave.addEventListener("click", saveSettings);

  // Tab switching
  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab!));
  });
});

// ---------------------------------------------------------------------------
// Settings (chrome.storage.local)
// ---------------------------------------------------------------------------

async function loadSettings(): Promise<void> {
  try {
    const result = await chrome.storage.local.get("seopilot_settings");
    if (result.seopilot_settings) {
      userSettings = {
        ...DEFAULT_SETTINGS,
        ...result.seopilot_settings,
        enabledChecks: {
          ...DEFAULT_SETTINGS.enabledChecks,
          ...(result.seopilot_settings.enabledChecks || {}),
        },
      };
    }
  } catch {
    // Use defaults if storage not available
  }
}

function openSettings(): void {
  // Sync checkbox states
  const checkboxes = settingsChecks.querySelectorAll<HTMLInputElement>(
    'input[type="checkbox"]',
  );
  checkboxes.forEach((cb) => {
    const checkId = cb.dataset.check!;
    cb.checked = userSettings.enabledChecks[checkId] !== false;
  });
  settingsPanel.classList.remove("hidden");
}

function closeSettings(): void {
  settingsPanel.classList.add("hidden");
}

async function saveSettings(): Promise<void> {
  const checkboxes = settingsChecks.querySelectorAll<HTMLInputElement>(
    'input[type="checkbox"]',
  );
  const enabledChecks: Record<string, boolean> = {};
  checkboxes.forEach((cb) => {
    enabledChecks[cb.dataset.check!] = cb.checked;
  });
  userSettings.enabledChecks = enabledChecks;

  try {
    await chrome.storage.local.set({ seopilot_settings: userSettings });
  } catch {
    // Ignore storage errors
  }

  closeSettings();

  // Re-render with new settings if we have results
  if (currentResult) {
    renderResults(currentResult);
  }
}

// ---------------------------------------------------------------------------
// Tab Switching
// ---------------------------------------------------------------------------

function switchTab(tabName: string): void {
  tabButtons.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabName);
  });
  tabContents.forEach((content) => {
    content.classList.toggle("active", content.id === `tab-${tabName}`);
  });
}

// ---------------------------------------------------------------------------
// Analysis
// ---------------------------------------------------------------------------

async function runAnalysis(): Promise<void> {
  showLoading();

  try {
    const [tab] = await chrome.tabs.query({
      active: true,
      currentWindow: true,
    });

    if (!tab?.id) {
      showError("No active tab found.");
      return;
    }

    const url = tab.url || "";
    if (
      url.startsWith("chrome://") ||
      url.startsWith("chrome-extension://") ||
      url.startsWith("about:") ||
      url.startsWith("edge://") ||
      url === ""
    ) {
      showError(
        "Cannot analyze browser internal pages. Navigate to a website and try again.",
      );
      return;
    }

    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["content.js"],
    });

    const result = results?.[0]?.result as AnalysisResult | undefined;

    if (!result) {
      showError("Analysis failed. The page may be blocking scripts.");
      return;
    }

    currentResult = result;
    renderResults(result);

    chrome.runtime.sendMessage({
      type: "UPDATE_BADGE",
      score: result.overallScore,
      color: result.scoreColor,
    });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    console.error("SEOPilot analysis error:", err);
    showError(`Analysis failed: ${msg}`);
  }
}

// ---------------------------------------------------------------------------
// UI State Management
// ---------------------------------------------------------------------------

function showLoading(): void {
  loadingEl.classList.remove("hidden");
  errorEl.classList.add("hidden");
  resultsEl.classList.add("hidden");
}

function showError(message: string): void {
  loadingEl.classList.add("hidden");
  errorEl.classList.remove("hidden");
  resultsEl.classList.add("hidden");
  errorMessage.textContent = message;
}

function showResults(): void {
  loadingEl.classList.add("hidden");
  errorEl.classList.add("hidden");
  resultsEl.classList.remove("hidden");
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderResults(result: AnalysisResult): void {
  // Page info
  const displayUrl =
    result.url.length > 60 ? result.url.substring(0, 57) + "..." : result.url;
  pageInfoEl.textContent = displayUrl;
  pageInfoEl.title = result.url;

  // Filter checks by settings
  const enabledChecks = result.checks.filter(
    (c) => userSettings.enabledChecks[c.id] !== false,
  );

  // Recalculate score for enabled checks only
  let totalWeight = 0;
  let weightedScore = 0;
  for (const check of enabledChecks) {
    totalWeight += check.weight;
    weightedScore += check.weight * check.score;
  }
  const displayScore =
    totalWeight > 0 ? Math.round(weightedScore / totalWeight) : 0;
  const displayColor =
    displayScore < 50 ? "red" : displayScore < 80 ? "yellow" : "green";

  // Score ring animation
  animateScore(displayScore, displayColor);

  // Checks list
  checksListEl.innerHTML = "";
  for (const check of enabledChecks) {
    checksListEl.appendChild(createCheckItem(check));
  }

  // Render social previews
  renderSocialPreviews(result);

  showResults();
}

function animateScore(score: number, color: string): void {
  const circumference = 2 * Math.PI * 52;

  const colorMap: Record<string, string> = {
    red: "#ef4444",
    yellow: "#f59e0b",
    green: "#22c55e",
  };

  scoreCircleEl.style.stroke = colorMap[color] || colorMap.red;

  const duration = 600;
  const startTime = Date.now();

  function tick() {
    const elapsed = Date.now() - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);

    const current = Math.round(score * eased);
    scoreValueEl.textContent = String(current);

    const currentOffset = circumference - (current / 100) * circumference;
    scoreCircleEl.style.strokeDashoffset = String(currentOffset);

    if (progress < 1) {
      requestAnimationFrame(tick);
    }
  }

  tick();

  const labels: Record<string, string> = {
    green: "Good",
    yellow: "Needs Work",
    red: "Poor",
  };
  scoreLabelEl.textContent = `SEO Score \u2014 ${labels[color] || ""}`;
}

function createCheckItem(check: CheckResult): HTMLElement {
  const item = document.createElement("div");
  item.className = "check-item";

  const header = document.createElement("div");
  header.className = "check-header";

  const statusIcons: Record<string, string> = {
    pass: "\u2713",
    warning: "!",
    fail: "\u2717",
  };

  header.innerHTML = `
    <div class="check-name">
      <div class="check-status-icon ${check.status}">${statusIcons[check.status]}</div>
      <span>${escapeHtml(check.name)}</span>
    </div>
    <span class="check-score" style="color: ${getStatusColor(check.status)}">${check.score}/100</span>
    <span class="check-arrow">&#9654;</span>
  `;

  const details = document.createElement("div");
  details.className = "check-details";

  if (check.issues.length === 0) {
    details.innerHTML =
      '<div class="check-pass-msg">\u2713 All checks passed</div>';
  } else {
    for (const issue of check.issues) {
      details.appendChild(createIssueItem(issue));
    }
  }

  const statsHtml = renderCheckStats(check);
  if (statsHtml) {
    const statsDiv = document.createElement("div");
    statsDiv.style.marginTop = "8px";
    statsDiv.style.paddingTop = "8px";
    statsDiv.style.borderTop = "1px solid var(--border-light)";
    statsDiv.innerHTML = statsHtml;
    details.appendChild(statsDiv);
  }

  header.addEventListener("click", () => {
    item.classList.toggle("expanded");
  });

  item.appendChild(header);
  item.appendChild(details);
  return item;
}

function createIssueItem(issue: {
  severity: string;
  message: string;
  recommendation: string;
}): HTMLElement {
  const el = document.createElement("div");
  el.className = "issue-item";
  el.innerHTML = `
    <span class="issue-badge ${issue.severity}">${issue.severity}</span>
    <div class="issue-content">
      <div class="issue-message">${escapeHtml(issue.message)}</div>
      <div class="issue-recommendation">${escapeHtml(issue.recommendation)}</div>
    </div>
  `;
  return el;
}

function renderCheckStats(check: CheckResult): string {
  const d = check.details as Record<string, unknown>;
  switch (check.id) {
    case "meta-title":
      return (
        detailRow("Title", truncate(String(d.title || "(empty)"), 50)) +
        detailRow("Length", `${d.length} chars`)
      );

    case "meta-description":
      return (
        detailRow(
          "Description",
          truncate(String(d.description || "(empty)"), 50),
        ) + detailRow("Length", `${d.length} chars`)
      );

    case "headings": {
      const counts = d.counts as Record<string, number>;
      const parts = Object.entries(counts)
        .filter(([, v]) => v > 0)
        .map(([k, v]) => `${k.toUpperCase()}: ${v}`)
        .join(", ");
      return (
        detailRow("Structure", parts || "No headings found") +
        (d.h1Text
          ? detailRow("H1 Text", truncate(String(d.h1Text), 50))
          : "")
      );
    }

    case "image-alt":
      return (
        detailRow("Total Images", String(d.totalImages)) +
        detailRow("With Alt", String(d.withAlt)) +
        detailRow("Without Alt", String(d.withoutAlt))
      );

    case "links":
      return (
        detailRow("Total Links", String(d.totalLinks)) +
        detailRow("Internal", String(d.internalLinks)) +
        detailRow("External", String(d.externalLinks)) +
        (Number(d.nofollowLinks) > 0
          ? detailRow("Nofollow", String(d.nofollowLinks))
          : "")
      );

    case "social-meta":
      return (
        detailRow("OG Tags", `${d.ogFieldsPresent}/5 present`) +
        detailRow("Twitter Tags", `${d.twFieldsPresent}/4 present`)
      );

    default:
      return "";
  }
}

// ---------------------------------------------------------------------------
// Social Media Previews
// ---------------------------------------------------------------------------

function renderSocialPreviews(result: AnalysisResult): void {
  const socialCheck = result.checks.find((c) => c.id === "social-meta");
  const titleCheck = result.checks.find((c) => c.id === "meta-title");
  const descCheck = result.checks.find((c) => c.id === "meta-description");

  const socialDetails = (socialCheck?.details || {}) as Record<string, unknown>;
  const og = (socialDetails.og || {}) as Record<string, string | null>;
  const tw = (socialDetails.twitter || {}) as Record<string, string | null>;

  const pageTitle =
    (titleCheck?.details as Record<string, unknown>)?.title as string || result.title;
  const pageDesc =
    (descCheck?.details as Record<string, unknown>)?.description as string || "";

  let hostname = "";
  try {
    hostname = new URL(result.url).hostname;
  } catch {
    hostname = result.url;
  }

  // Fallback logic: OG > Twitter > page meta > empty
  const effectiveTitle = og.title || tw.title || pageTitle || "(No title)";
  const effectiveDesc =
    og.description || tw.description || pageDesc || "(No description)";
  const effectiveImage = og.image || tw.image || null;

  // Google SERP
  serpUrl.textContent = result.url;
  serpTitle.textContent = truncate(effectiveTitle, 60);
  serpDesc.textContent = truncate(effectiveDesc, 160);

  // Twitter/X
  if (effectiveImage) {
    twImage.innerHTML = `<img src="${escapeHtml(effectiveImage)}" alt="Preview" onerror="this.parentElement.textContent='No image available'">`;
  } else {
    twImage.textContent = "No image available";
  }
  twTitle.textContent = truncate(tw.title || effectiveTitle, 70);
  twDesc.textContent = truncate(tw.description || effectiveDesc, 200);
  twDomain.textContent = hostname;

  // Facebook
  if (effectiveImage) {
    fbImage.innerHTML = `<img src="${escapeHtml(effectiveImage)}" alt="Preview" onerror="this.parentElement.textContent='No image available'">`;
  } else {
    fbImage.textContent = "No image available";
  }
  fbDomain.textContent = hostname.toUpperCase();
  fbTitle.textContent = truncate(og.title || effectiveTitle, 65);
  fbDesc.textContent = truncate(og.description || effectiveDesc, 200);
}

// ---------------------------------------------------------------------------
// Clipboard Export (Markdown)
// ---------------------------------------------------------------------------

async function copyToClipboard(): Promise<void> {
  if (!currentResult) return;

  const r = currentResult;
  const enabledChecks = r.checks.filter(
    (c) => userSettings.enabledChecks[c.id] !== false,
  );

  let md = `# SEO Analysis Report\n\n`;
  md += `**URL:** ${r.url}\n`;
  md += `**Score:** ${r.overallScore}/100\n`;
  md += `**Date:** ${new Date(r.timestamp).toLocaleString()}\n\n`;
  md += `---\n\n`;

  for (const check of enabledChecks) {
    const icon = check.status === "pass" ? "\u2705" : check.status === "warning" ? "\u26a0\ufe0f" : "\u274c";
    md += `## ${icon} ${check.name} (${check.score}/100)\n\n`;

    if (check.issues.length === 0) {
      md += `All checks passed.\n\n`;
    } else {
      for (const issue of check.issues) {
        md += `- **[${issue.severity.toUpperCase()}]** ${issue.message}\n`;
        md += `  - *Fix:* ${issue.recommendation}\n`;
      }
      md += `\n`;
    }
  }

  md += `---\n*Generated by SEOPilot Lite*\n`;

  try {
    await navigator.clipboard.writeText(md);
    showToast("Copied to clipboard!");
  } catch {
    // Fallback: select and copy
    const textarea = document.createElement("textarea");
    textarea.value = md;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    document.body.removeChild(textarea);
    showToast("Copied to clipboard!");
  }
}

function showToast(message: string): void {
  toastEl.textContent = message;
  toastEl.classList.remove("hidden");
  setTimeout(() => {
    toastEl.classList.add("hidden");
  }, 2000);
}

// ---------------------------------------------------------------------------
// Export function for tests
// ---------------------------------------------------------------------------

export function formatMarkdownReport(result: AnalysisResult, settings: UserSettings): string {
  const enabledChecks = result.checks.filter(
    (c) => settings.enabledChecks[c.id] !== false,
  );

  let md = `# SEO Analysis Report\n\n`;
  md += `**URL:** ${result.url}\n`;
  md += `**Score:** ${result.overallScore}/100\n`;
  md += `**Date:** ${new Date(result.timestamp).toLocaleString()}\n\n`;
  md += `---\n\n`;

  for (const check of enabledChecks) {
    const icon = check.status === "pass" ? "\u2705" : check.status === "warning" ? "\u26a0\ufe0f" : "\u274c";
    md += `## ${icon} ${check.name} (${check.score}/100)\n\n`;

    if (check.issues.length === 0) {
      md += `All checks passed.\n\n`;
    } else {
      for (const issue of check.issues) {
        md += `- **[${issue.severity.toUpperCase()}]** ${issue.message}\n`;
        md += `  - *Fix:* ${issue.recommendation}\n`;
      }
      md += `\n`;
    }
  }

  md += `---\n*Generated by SEOPilot Lite*\n`;
  return md;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getStatusColor(status: string): string {
  const colors: Record<string, string> = {
    pass: "#22c55e",
    warning: "#f59e0b",
    fail: "#ef4444",
  };
  return colors[status] || "#6b7280";
}

function escapeHtml(text: string): string {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function truncate(str: string, max: number): string {
  return str.length > max ? str.substring(0, max - 3) + "..." : str;
}

function detailRow(label: string, value: string): string {
  return `<div class="detail-row"><span class="detail-label">${escapeHtml(label)}</span><span class="detail-value" title="${escapeHtml(value)}">${escapeHtml(value)}</span></div>`;
}
