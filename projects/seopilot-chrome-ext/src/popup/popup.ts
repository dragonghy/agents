/**
 * Popup Script — Controls the popup UI and triggers analysis.
 *
 * When the popup opens, it injects the content script into the active tab,
 * receives the analysis results, and renders them.
 */

import type { AnalysisResult, CheckResult } from "../content/seo-checks";

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

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let currentResult: AnalysisResult | null = null;

// ---------------------------------------------------------------------------
// Main Entry
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  runAnalysis();
  retryBtn.addEventListener("click", runAnalysis);
});

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

    // Check for restricted URLs
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

    // Inject and execute the content script
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

    // Update badge
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

  // Score ring animation
  animateScore(result.overallScore, result.scoreColor);

  // Checks list
  checksListEl.innerHTML = "";
  for (const check of result.checks) {
    checksListEl.appendChild(createCheckItem(check));
  }

  showResults();
}

function animateScore(score: number, color: string): void {
  const circumference = 2 * Math.PI * 52; // r=52
  const offset = circumference - (score / 100) * circumference;

  const colorMap: Record<string, string> = {
    red: "#ef4444",
    yellow: "#f59e0b",
    green: "#22c55e",
  };

  scoreCircleEl.style.stroke = colorMap[color] || colorMap.red;

  // Animate
  let current = 0;
  const duration = 600;
  const startTime = Date.now();

  function tick() {
    const elapsed = Date.now() - startTime;
    const progress = Math.min(elapsed / duration, 1);
    // Ease out cubic
    const eased = 1 - Math.pow(1 - progress, 3);

    current = Math.round(score * eased);
    scoreValueEl.textContent = String(current);

    const currentOffset = circumference - (current / 100) * circumference;
    scoreCircleEl.style.strokeDashoffset = String(currentOffset);

    if (progress < 1) {
      requestAnimationFrame(tick);
    }
  }

  tick();

  // Score label
  const labels: Record<string, string> = {
    green: "Good",
    yellow: "Needs Work",
    red: "Poor",
  };
  scoreLabelEl.textContent = `SEO Score — ${labels[color] || ""}`;
}

function createCheckItem(check: CheckResult): HTMLElement {
  const item = document.createElement("div");
  item.className = "check-item";

  // Header
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

  // Details panel
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

  // Add detail stats
  const statsHtml = renderCheckStats(check);
  if (statsHtml) {
    const statsDiv = document.createElement("div");
    statsDiv.style.marginTop = "8px";
    statsDiv.style.paddingTop = "8px";
    statsDiv.style.borderTop = "1px solid var(--border-light)";
    statsDiv.innerHTML = statsHtml;
    details.appendChild(statsDiv);
  }

  // Toggle expand
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
      return detailRow("Title", truncate(String(d.title || "(empty)"), 50)) +
        detailRow("Length", `${d.length} chars`);

    case "meta-description":
      return detailRow("Description", truncate(String(d.description || "(empty)"), 50)) +
        detailRow("Length", `${d.length} chars`);

    case "headings": {
      const counts = d.counts as Record<string, number>;
      const parts = Object.entries(counts)
        .filter(([, v]) => v > 0)
        .map(([k, v]) => `${k.toUpperCase()}: ${v}`)
        .join(", ");
      return detailRow("Structure", parts || "No headings found") +
        (d.h1Text ? detailRow("H1 Text", truncate(String(d.h1Text), 50)) : "");
    }

    case "image-alt":
      return detailRow("Total Images", String(d.totalImages)) +
        detailRow("With Alt", String(d.withAlt)) +
        detailRow("Without Alt", String(d.withoutAlt));

    case "links":
      return detailRow("Total Links", String(d.totalLinks)) +
        detailRow("Internal", String(d.internalLinks)) +
        detailRow("External", String(d.externalLinks)) +
        (Number(d.nofollowLinks) > 0
          ? detailRow("Nofollow", String(d.nofollowLinks))
          : "");

    case "social-meta":
      return detailRow("OG Tags", `${d.ogFieldsPresent}/5 present`) +
        detailRow("Twitter Tags", `${d.twFieldsPresent}/4 present`);

    default:
      return "";
  }
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
