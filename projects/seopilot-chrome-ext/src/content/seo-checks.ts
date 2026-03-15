/**
 * SEO Analysis Engine — DOM-based SEO checker for any webpage.
 *
 * Adapted from SEOPilot Shopify App's seo-rules.server.ts.
 * Instead of Shopify GraphQL data, this reads directly from the page DOM.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type IssueSeverity = "critical" | "warning" | "info";
export type CheckStatus = "pass" | "warning" | "fail";

export interface SeoIssue {
  ruleId: string;
  severity: IssueSeverity;
  message: string;
  currentValue?: string | number | null;
  recommendation: string;
}

export interface CheckResult {
  id: string;
  name: string;
  status: CheckStatus;
  score: number; // 0-100
  weight: number;
  issues: SeoIssue[];
  details: Record<string, unknown>;
}

export interface AnalysisResult {
  url: string;
  title: string;
  overallScore: number;
  scoreColor: "red" | "yellow" | "green";
  checks: CheckResult[];
  timestamp: number;
}

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function getScoreColor(score: number): "red" | "yellow" | "green" {
  if (score < 50) return "red";
  if (score < 80) return "yellow";
  return "green";
}

function getCheckStatus(score: number): CheckStatus {
  if (score >= 80) return "pass";
  if (score >= 50) return "warning";
  return "fail";
}

// ---------------------------------------------------------------------------
// Check 1: Meta Title
// ---------------------------------------------------------------------------

export function checkMetaTitle(doc: Document): CheckResult {
  const issues: SeoIssue[] = [];
  const titleEl = doc.querySelector("title");
  const metaTitle =
    doc.querySelector('meta[property="og:title"]')?.getAttribute("content") ||
    null;
  const title = titleEl?.textContent?.trim() || "";
  const length = title.length;

  let score = 100;

  // Existence
  if (length === 0) {
    issues.push({
      ruleId: "meta-title-missing",
      severity: "critical",
      message: "Page has no title tag. This is critical for SEO.",
      currentValue: null,
      recommendation:
        "Add a <title> tag with a descriptive title (30-60 characters).",
    });
    score = 0;
  } else {
    // Length check
    if (length < 30) {
      issues.push({
        ruleId: "meta-title-short",
        severity: "warning",
        message: `Title is too short (${length} chars). Aim for 30-60 characters.`,
        currentValue: length,
        recommendation:
          "Expand the title to include more descriptive keywords (30-60 chars).",
      });
      score = 50;
    } else if (length > 60) {
      issues.push({
        ruleId: "meta-title-long",
        severity: "warning",
        message: `Title is too long (${length} chars). Search engines truncate after ~60 characters.`,
        currentValue: length,
        recommendation: "Shorten the title to 60 characters or fewer.",
      });
      score = 60;
    }

    // Keyword quality: check for generic/boilerplate titles
    const generic = [
      "home",
      "untitled",
      "document",
      "page",
      "welcome",
      "website",
    ];
    if (generic.includes(title.toLowerCase())) {
      issues.push({
        ruleId: "meta-title-generic",
        severity: "warning",
        message: `Title appears generic ("${title}"). Use a unique, descriptive title.`,
        currentValue: title,
        recommendation:
          "Replace with a title that describes the page content and includes target keywords.",
      });
      score = Math.min(score, 40);
    }
  }

  return {
    id: "meta-title",
    name: "Meta Title",
    status: getCheckStatus(score),
    score,
    weight: 20,
    issues,
    details: { title, length },
  };
}

// ---------------------------------------------------------------------------
// Check 2: Meta Description
// ---------------------------------------------------------------------------

export function checkMetaDescription(doc: Document): CheckResult {
  const issues: SeoIssue[] = [];
  const metaDesc =
    doc
      .querySelector('meta[name="description"]')
      ?.getAttribute("content")
      ?.trim() || "";
  const length = metaDesc.length;

  let score = 100;

  if (length === 0) {
    issues.push({
      ruleId: "meta-desc-missing",
      severity: "critical",
      message:
        "Meta description is missing. Search engines use this in results snippets.",
      currentValue: null,
      recommendation:
        "Add a <meta name='description'> tag with a compelling description (120-160 characters).",
    });
    score = 0;
  } else {
    if (length < 120) {
      issues.push({
        ruleId: "meta-desc-short",
        severity: "warning",
        message: `Meta description is too short (${length} chars). Aim for 120-160 characters.`,
        currentValue: length,
        recommendation:
          "Expand the description with more detail about the page content (120-160 chars).",
      });
      score = 50;
    } else if (length > 160) {
      issues.push({
        ruleId: "meta-desc-long",
        severity: "warning",
        message: `Meta description is too long (${length} chars). It may be truncated in search results.`,
        currentValue: length,
        recommendation:
          "Shorten the description to 160 characters or fewer to avoid truncation.",
      });
      score = 70;
    }
  }

  return {
    id: "meta-description",
    name: "Meta Description",
    status: getCheckStatus(score),
    score,
    weight: 20,
    issues,
    details: { description: metaDesc, length },
  };
}

// ---------------------------------------------------------------------------
// Check 3: Heading Structure
// ---------------------------------------------------------------------------

export function checkHeadings(doc: Document): CheckResult {
  const issues: SeoIssue[] = [];

  const h1s = doc.querySelectorAll("h1");
  const h2s = doc.querySelectorAll("h2");
  const h3s = doc.querySelectorAll("h3");
  const h4s = doc.querySelectorAll("h4");
  const h5s = doc.querySelectorAll("h5");
  const h6s = doc.querySelectorAll("h6");

  const h1Count = h1s.length;
  const headingCounts = {
    h1: h1Count,
    h2: h2s.length,
    h3: h3s.length,
    h4: h4s.length,
    h5: h5s.length,
    h6: h6s.length,
  };

  let score = 100;

  // H1 uniqueness check
  if (h1Count === 0) {
    issues.push({
      ruleId: "heading-no-h1",
      severity: "critical",
      message: "No H1 tag found. Every page should have exactly one H1.",
      currentValue: 0,
      recommendation:
        "Add a single H1 tag that describes the main topic of the page.",
    });
    score = 30;
  } else if (h1Count > 1) {
    issues.push({
      ruleId: "heading-multiple-h1",
      severity: "warning",
      message: `Found ${h1Count} H1 tags. Each page should have exactly one H1.`,
      currentValue: h1Count,
      recommendation:
        "Keep only one H1 tag and convert others to H2 or lower.",
    });
    score = 60;
  }

  // Check for heading level skipping (e.g., H1 -> H3 without H2)
  const levels = [h1Count, h2s.length, h3s.length, h4s.length, h5s.length, h6s.length];
  let prevUsed = -1;
  let hasSkip = false;

  for (let i = 0; i < levels.length; i++) {
    if (levels[i] > 0) {
      if (prevUsed >= 0 && i - prevUsed > 1) {
        hasSkip = true;
        break;
      }
      prevUsed = i;
    }
  }

  if (hasSkip) {
    issues.push({
      ruleId: "heading-skip-level",
      severity: "info",
      message:
        "Heading levels are skipped (e.g., H1 to H3 without H2). Use a logical hierarchy.",
      currentValue: JSON.stringify(headingCounts),
      recommendation:
        "Use heading levels sequentially: H1 > H2 > H3, without skipping levels.",
    });
    score = Math.min(score, 70);
  }

  // H1 text length
  if (h1Count === 1) {
    const h1Text = h1s[0].textContent?.trim() || "";
    if (h1Text.length < 5) {
      issues.push({
        ruleId: "heading-h1-too-short",
        severity: "info",
        message: `H1 tag is very short ("${h1Text}"). Use a descriptive heading.`,
        currentValue: h1Text,
        recommendation:
          "Make the H1 descriptive enough to convey the page's main topic.",
      });
      score = Math.min(score, 75);
    }
  }

  return {
    id: "headings",
    name: "Heading Structure",
    status: getCheckStatus(score),
    score,
    weight: 15,
    issues,
    details: {
      counts: headingCounts,
      h1Text: h1Count > 0 ? h1s[0].textContent?.trim() : null,
    },
  };
}

// ---------------------------------------------------------------------------
// Check 4: Image Alt Text
// ---------------------------------------------------------------------------

export function checkImageAlt(doc: Document): CheckResult {
  const issues: SeoIssue[] = [];
  const images = doc.querySelectorAll("img");
  const totalImages = images.length;

  if (totalImages === 0) {
    return {
      id: "image-alt",
      name: "Image Alt Text",
      status: "pass",
      score: 100,
      weight: 15,
      issues: [],
      details: { totalImages: 0, withAlt: 0, withoutAlt: 0, lowQualityAlt: 0 },
    };
  }

  let withAlt = 0;
  let withoutAlt = 0;
  let lowQualityAlt = 0;

  const lowQualityPatterns = [
    /^image$/i,
    /^img$/i,
    /^photo$/i,
    /^picture$/i,
    /^screenshot$/i,
    /^untitled$/i,
    /^\d+$/,
    /^DSC/i,
    /^IMG_/i,
  ];

  images.forEach((img) => {
    const alt = img.getAttribute("alt");
    if (alt === null || alt.trim() === "") {
      withoutAlt++;
    } else {
      withAlt++;
      if (lowQualityPatterns.some((p) => p.test(alt.trim()))) {
        lowQualityAlt++;
      }
    }
  });

  let score: number;

  if (withoutAlt > 0) {
    const ratio = withAlt / totalImages;
    score = Math.round(ratio * 100);

    const severity: IssueSeverity =
      withoutAlt === totalImages ? "critical" : "warning";
    issues.push({
      ruleId: "image-alt-missing",
      severity,
      message: `${withoutAlt} of ${totalImages} image(s) missing alt text.`,
      currentValue: `${withoutAlt}/${totalImages} missing`,
      recommendation:
        "Add descriptive alt text to all images for accessibility and SEO.",
    });
  } else {
    score = 100;
  }

  if (lowQualityAlt > 0) {
    issues.push({
      ruleId: "image-alt-low-quality",
      severity: "info",
      message: `${lowQualityAlt} image(s) have generic/low-quality alt text (e.g., "image", "photo").`,
      currentValue: lowQualityAlt,
      recommendation:
        "Replace generic alt text with descriptive text that explains the image content.",
    });
    score = Math.min(score, 80);
  }

  return {
    id: "image-alt",
    name: "Image Alt Text",
    status: getCheckStatus(score),
    score,
    weight: 15,
    issues,
    details: { totalImages, withAlt, withoutAlt, lowQualityAlt },
  };
}

// ---------------------------------------------------------------------------
// Check 5: Link Analysis
// ---------------------------------------------------------------------------

export function checkLinks(doc: Document): CheckResult {
  const issues: SeoIssue[] = [];
  const links = doc.querySelectorAll("a[href]");
  const pageUrl = doc.location?.href || "";
  let pageHostname = "";
  try {
    pageHostname = new URL(pageUrl).hostname;
  } catch {
    // ignore
  }

  let internalLinks = 0;
  let externalLinks = 0;
  let nofollowLinks = 0;
  let emptyLinks = 0;
  let totalLinks = 0;

  links.forEach((link) => {
    const href = link.getAttribute("href")?.trim() || "";
    if (!href || href === "#" || href.startsWith("javascript:")) {
      emptyLinks++;
      return;
    }

    totalLinks++;

    try {
      const url = new URL(href, pageUrl);
      if (url.hostname === pageHostname) {
        internalLinks++;
      } else {
        externalLinks++;
      }
    } catch {
      internalLinks++; // Relative URLs are internal
    }

    const rel = link.getAttribute("rel") || "";
    if (rel.includes("nofollow")) {
      nofollowLinks++;
    }
  });

  let score = 100;

  if (totalLinks === 0) {
    issues.push({
      ruleId: "links-none",
      severity: "warning",
      message: "No links found on the page. Internal linking helps SEO.",
      currentValue: 0,
      recommendation:
        "Add internal links to relevant pages and external links to authoritative sources.",
    });
    score = 50;
  } else {
    if (internalLinks === 0) {
      issues.push({
        ruleId: "links-no-internal",
        severity: "warning",
        message: "No internal links found. Internal linking improves crawlability.",
        currentValue: 0,
        recommendation:
          "Add links to other pages on your site for better navigation and SEO.",
      });
      score = Math.min(score, 60);
    }

    if (emptyLinks > 3) {
      issues.push({
        ruleId: "links-empty",
        severity: "info",
        message: `${emptyLinks} link(s) have empty or JavaScript-only href attributes.`,
        currentValue: emptyLinks,
        recommendation:
          "Use proper href values for links. Empty or JavaScript hrefs reduce crawlability.",
      });
      score = Math.min(score, 80);
    }

    const nofollowRatio = totalLinks > 0 ? nofollowLinks / totalLinks : 0;
    if (nofollowRatio > 0.5 && nofollowLinks > 5) {
      issues.push({
        ruleId: "links-excessive-nofollow",
        severity: "info",
        message: `${nofollowLinks} of ${totalLinks} links are nofollow (${Math.round(nofollowRatio * 100)}%).`,
        currentValue: `${nofollowLinks}/${totalLinks}`,
        recommendation:
          "Excessive nofollow can reduce link equity. Use nofollow only for untrusted or paid links.",
      });
      score = Math.min(score, 85);
    }
  }

  return {
    id: "links",
    name: "Link Analysis",
    status: getCheckStatus(score),
    score,
    weight: 15,
    issues,
    details: {
      totalLinks,
      internalLinks,
      externalLinks,
      nofollowLinks,
      emptyLinks,
    },
  };
}

// ---------------------------------------------------------------------------
// Check 6: Open Graph / Twitter Card
// ---------------------------------------------------------------------------

export function checkSocialMeta(doc: Document): CheckResult {
  const issues: SeoIssue[] = [];

  const getMeta = (attr: string, value: string): string | null =>
    doc.querySelector(`meta[${attr}="${value}"]`)?.getAttribute("content") ||
    null;

  const ogTitle = getMeta("property", "og:title");
  const ogDescription = getMeta("property", "og:description");
  const ogImage = getMeta("property", "og:image");
  const ogType = getMeta("property", "og:type");
  const ogUrl = getMeta("property", "og:url");

  const twitterCard = getMeta("name", "twitter:card");
  const twitterTitle = getMeta("name", "twitter:title");
  const twitterDescription = getMeta("name", "twitter:description");
  const twitterImage = getMeta("name", "twitter:image");

  let score = 100;
  let ogFieldsPresent = 0;
  let twFieldsPresent = 0;
  const ogTotal = 5;
  const twTotal = 4;

  // Open Graph checks
  if (ogTitle) ogFieldsPresent++;
  if (ogDescription) ogFieldsPresent++;
  if (ogImage) ogFieldsPresent++;
  if (ogType) ogFieldsPresent++;
  if (ogUrl) ogFieldsPresent++;

  if (twitterCard) twFieldsPresent++;
  if (twitterTitle) twFieldsPresent++;
  if (twitterDescription) twFieldsPresent++;
  if (twitterImage) twFieldsPresent++;

  if (ogFieldsPresent === 0 && twFieldsPresent === 0) {
    issues.push({
      ruleId: "social-meta-missing",
      severity: "critical",
      message:
        "No Open Graph or Twitter Card meta tags found. Social sharing will use fallback data.",
      recommendation:
        "Add og:title, og:description, og:image and twitter:card tags for better social media previews.",
    });
    score = 0;
  } else {
    // OG completeness
    if (ogFieldsPresent < 3) {
      const missing: string[] = [];
      if (!ogTitle) missing.push("og:title");
      if (!ogDescription) missing.push("og:description");
      if (!ogImage) missing.push("og:image");
      if (!ogType) missing.push("og:type");
      if (!ogUrl) missing.push("og:url");

      issues.push({
        ruleId: "og-incomplete",
        severity: ogFieldsPresent === 0 ? "warning" : "info",
        message: `Open Graph tags incomplete. Missing: ${missing.join(", ")}.`,
        currentValue: `${ogFieldsPresent}/${ogTotal} present`,
        recommendation: `Add the missing OG tags: ${missing.join(", ")}.`,
      });
    }

    // Twitter Card completeness
    if (twFieldsPresent < 2) {
      const missing: string[] = [];
      if (!twitterCard) missing.push("twitter:card");
      if (!twitterTitle) missing.push("twitter:title");
      if (!twitterDescription) missing.push("twitter:description");
      if (!twitterImage) missing.push("twitter:image");

      issues.push({
        ruleId: "twitter-card-incomplete",
        severity: twFieldsPresent === 0 ? "info" : "info",
        message: `Twitter Card tags incomplete. Missing: ${missing.join(", ")}.`,
        currentValue: `${twFieldsPresent}/${twTotal} present`,
        recommendation: `Add the missing Twitter Card tags: ${missing.join(", ")}.`,
      });
    }

    // Score based on coverage
    const totalPresent = ogFieldsPresent + twFieldsPresent;
    const totalFields = ogTotal + twTotal;
    score = Math.round((totalPresent / totalFields) * 100);
  }

  return {
    id: "social-meta",
    name: "OG / Twitter Card",
    status: getCheckStatus(score),
    score,
    weight: 15,
    issues,
    details: {
      og: { title: ogTitle, description: ogDescription, image: ogImage, type: ogType, url: ogUrl },
      twitter: { card: twitterCard, title: twitterTitle, description: twitterDescription, image: twitterImage },
      ogFieldsPresent,
      twFieldsPresent,
    },
  };
}

// ---------------------------------------------------------------------------
// Main Analysis Function
// ---------------------------------------------------------------------------

export function analyzePage(doc: Document): AnalysisResult {
  const checks: CheckResult[] = [
    checkMetaTitle(doc),
    checkMetaDescription(doc),
    checkHeadings(doc),
    checkImageAlt(doc),
    checkLinks(doc),
    checkSocialMeta(doc),
  ];

  // Calculate weighted overall score
  let totalWeight = 0;
  let weightedScore = 0;
  for (const check of checks) {
    totalWeight += check.weight;
    weightedScore += check.weight * check.score;
  }

  const overallScore =
    totalWeight > 0 ? Math.round(weightedScore / totalWeight) : 0;

  return {
    url: doc.location?.href || "",
    title: doc.title || "(No title)",
    overallScore,
    scoreColor: getScoreColor(overallScore),
    checks,
    timestamp: Date.now(),
  };
}
