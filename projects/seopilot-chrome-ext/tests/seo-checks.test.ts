/**
 * Tests for the SEO analysis engine.
 *
 * Since the analysis engine works on Document objects, we create
 * mock DOM documents using JSDOM-like string parsing.
 */

import { describe, it, expect, beforeEach } from "vitest";
import {
  checkMetaTitle,
  checkMetaDescription,
  checkHeadings,
  checkImageAlt,
  checkLinks,
  checkSocialMeta,
  analyzePage,
  type AnalysisResult,
  type CheckResult,
} from "../src/content/seo-checks";

// ---------------------------------------------------------------------------
// Helper: create a minimal Document-like object from HTML string
// ---------------------------------------------------------------------------

function createDoc(html: string, url = "https://example.com/page"): Document {
  // Use a real DOMParser-like approach with JSDOM via a simple string-based doc
  // Since vitest runs in node, we'll create a mock document

  // Parse HTML to extract elements
  const doc = new MockDocument(html, url);
  return doc as unknown as Document;
}

/**
 * Minimal mock Document for testing.
 * Implements querySelector, querySelectorAll, title, and location.
 */
class MockDocument {
  private html: string;
  private _url: string;
  private _title: string;

  constructor(html: string, url: string) {
    this.html = html;
    this._url = url;

    // Extract title from <title> tag
    const titleMatch = html.match(/<title[^>]*>(.*?)<\/title>/is);
    this._title = titleMatch ? titleMatch[1].trim() : "";
  }

  get title(): string {
    return this._title;
  }

  get location(): { href: string } {
    return { href: this._url };
  }

  querySelector(selector: string): MockElement | null {
    // Handle meta tags
    if (selector.startsWith("meta[")) {
      return this.findMeta(selector);
    }
    // Handle title tag
    if (selector === "title") {
      const match = this.html.match(/<title[^>]*>(.*?)<\/title>/is);
      if (match) {
        return new MockElement("title", { textContent: match[1].trim() });
      }
      return null;
    }
    return null;
  }

  querySelectorAll(selector: string): MockElement[] {
    // Handle heading tags
    const headingMatch = selector.match(/^(h[1-6])$/i);
    if (headingMatch) {
      const tag = headingMatch[1].toLowerCase();
      const regex = new RegExp(
        `<${tag}[^>]*>(.*?)</${tag}>`,
        "gis",
      );
      const results: MockElement[] = [];
      let match;
      while ((match = regex.exec(this.html)) !== null) {
        results.push(
          new MockElement(tag, { textContent: match[1].replace(/<[^>]*>/g, "").trim() }),
        );
      }
      return results;
    }

    // Handle img tags
    if (selector === "img") {
      const regex = /<img\s[^>]*>/gi;
      const results: MockElement[] = [];
      let match;
      while ((match = regex.exec(this.html)) !== null) {
        const tag = match[0];
        const alt = tag.match(/alt="([^"]*)"/i)?.[1] ?? null;
        results.push(new MockElement("img", {}, { alt }));
      }
      return results;
    }

    // Handle a[href] tags
    if (selector === "a[href]") {
      const regex = /<a\s[^>]*href="([^"]*)"[^>]*(?:rel="([^"]*)")?[^>]*>/gi;
      const results: MockElement[] = [];
      let match;
      while ((match = regex.exec(this.html)) !== null) {
        const fullTag = match[0];
        const href = match[1];
        const relMatch = fullTag.match(/rel="([^"]*)"/i);
        const rel = relMatch ? relMatch[1] : null;
        results.push(new MockElement("a", {}, { href, rel }));
      }
      return results;
    }

    return [];
  }

  private findMeta(selector: string): MockElement | null {
    // Parse selector like meta[name="description"] or meta[property="og:title"]
    const attrMatch = selector.match(/meta\[(\w+)="([^"]+)"\]/);
    if (!attrMatch) return null;

    const [, attrName, attrValue] = attrMatch;
    const regex = new RegExp(
      `<meta\\s[^>]*${attrName}="${attrValue}"[^>]*>`,
      "i",
    );
    const match = this.html.match(regex);
    if (!match) return null;

    const contentMatch = match[0].match(/content="([^"]*)"/i);
    return new MockElement("meta", {}, { content: contentMatch?.[1] || null });
  }
}

class MockElement {
  tag: string;
  textContent: string;
  private attrs: Record<string, string | null>;

  constructor(
    tag: string,
    props: { textContent?: string } = {},
    attrs: Record<string, string | null> = {},
  ) {
    this.tag = tag;
    this.textContent = props.textContent ?? "";
    this.attrs = attrs;
  }

  getAttribute(name: string): string | null {
    return this.attrs[name] ?? null;
  }
}

// ===========================================================================
// Tests
// ===========================================================================

describe("checkMetaTitle", () => {
  it("should pass for a good title (30-60 chars)", () => {
    const doc = createDoc(
      '<html><head><title>Best Running Shoes for Marathon Training 2024</title></head></html>',
    );
    const result = checkMetaTitle(doc);
    expect(result.status).toBe("pass");
    expect(result.score).toBe(100);
    expect(result.issues).toHaveLength(0);
  });

  it("should fail for missing title", () => {
    const doc = createDoc("<html><head></head><body>Hello</body></html>");
    const result = checkMetaTitle(doc);
    expect(result.status).toBe("fail");
    expect(result.score).toBe(0);
    expect(result.issues).toHaveLength(1);
    expect(result.issues[0].severity).toBe("critical");
  });

  it("should warn for short title", () => {
    const doc = createDoc("<html><head><title>Hello</title></head></html>");
    const result = checkMetaTitle(doc);
    expect(result.status).toBe("warning");
    expect(result.score).toBe(50);
  });

  it("should warn for long title", () => {
    const doc = createDoc(
      `<html><head><title>${"A".repeat(70)} - Too Long Title For Search Engines</title></head></html>`,
    );
    const result = checkMetaTitle(doc);
    expect(result.status).toBe("warning");
    expect(result.score).toBe(60);
  });

  it("should warn for generic title", () => {
    const doc = createDoc("<html><head><title>Home</title></head></html>");
    const result = checkMetaTitle(doc);
    expect(result.score).toBeLessThanOrEqual(40);
  });
});

describe("checkMetaDescription", () => {
  it("should pass for a good description (120-160 chars)", () => {
    const desc = "A".repeat(140);
    const doc = createDoc(
      `<html><head><meta name="description" content="${desc}"></head></html>`,
    );
    const result = checkMetaDescription(doc);
    expect(result.status).toBe("pass");
    expect(result.score).toBe(100);
  });

  it("should fail for missing description", () => {
    const doc = createDoc("<html><head></head></html>");
    const result = checkMetaDescription(doc);
    expect(result.status).toBe("fail");
    expect(result.score).toBe(0);
    expect(result.issues[0].severity).toBe("critical");
  });

  it("should warn for short description", () => {
    const doc = createDoc(
      '<html><head><meta name="description" content="Too short"></head></html>',
    );
    const result = checkMetaDescription(doc);
    expect(result.status).toBe("warning");
    expect(result.score).toBe(50);
  });

  it("should warn (but not fail) for long description", () => {
    const desc = "A".repeat(200);
    const doc = createDoc(
      `<html><head><meta name="description" content="${desc}"></head></html>`,
    );
    const result = checkMetaDescription(doc);
    expect(result.status).toBe("warning");
    expect(result.score).toBe(70);
  });
});

describe("checkHeadings", () => {
  it("should pass for single H1 with proper hierarchy", () => {
    const doc = createDoc(
      "<html><body><h1>Main Title</h1><h2>Sub</h2><h3>Detail</h3></body></html>",
    );
    const result = checkHeadings(doc);
    expect(result.status).toBe("pass");
    expect(result.score).toBe(100);
  });

  it("should fail for no H1", () => {
    const doc = createDoc(
      "<html><body><h2>Sub Title</h2><p>Content</p></body></html>",
    );
    const result = checkHeadings(doc);
    expect(result.status).toBe("fail");
    expect(result.score).toBe(30);
  });

  it("should warn for multiple H1 tags", () => {
    const doc = createDoc(
      "<html><body><h1>First</h1><h1>Second</h1></body></html>",
    );
    const result = checkHeadings(doc);
    expect(result.status).toBe("warning");
    expect(result.score).toBe(60);
  });

  it("should warn for heading level skip", () => {
    const doc = createDoc(
      "<html><body><h1>Title</h1><h3>Skipped H2</h3></body></html>",
    );
    const result = checkHeadings(doc);
    // Score should be <= 70 due to skip
    expect(result.score).toBeLessThanOrEqual(70);
    expect(result.issues.some((i) => i.ruleId === "heading-skip-level")).toBe(true);
  });
});

describe("checkImageAlt", () => {
  it("should pass when all images have alt text", () => {
    const doc = createDoc(
      '<html><body><img src="a.jpg" alt="A photo"><img src="b.jpg" alt="B photo"></body></html>',
    );
    const result = checkImageAlt(doc);
    expect(result.status).toBe("pass");
    expect(result.score).toBe(100);
  });

  it("should pass when no images exist", () => {
    const doc = createDoc("<html><body><p>No images</p></body></html>");
    const result = checkImageAlt(doc);
    expect(result.status).toBe("pass");
    expect(result.score).toBe(100);
  });

  it("should fail when all images missing alt", () => {
    const doc = createDoc(
      '<html><body><img src="a.jpg"><img src="b.jpg"></body></html>',
    );
    const result = checkImageAlt(doc);
    expect(result.status).toBe("fail");
    expect(result.score).toBe(0);
    expect(result.issues[0].severity).toBe("critical");
  });

  it("should warn for partial alt text coverage", () => {
    const doc = createDoc(
      '<html><body><img src="a.jpg" alt="Good"><img src="b.jpg"></body></html>',
    );
    const result = checkImageAlt(doc);
    expect(result.status).toBe("warning");
    expect(result.score).toBe(50);
  });

  it("should note low-quality alt text", () => {
    const doc = createDoc(
      '<html><body><img src="a.jpg" alt="image"><img src="b.jpg" alt="photo"></body></html>',
    );
    const result = checkImageAlt(doc);
    expect(
      result.issues.some((i) => i.ruleId === "image-alt-low-quality"),
    ).toBe(true);
  });
});

describe("checkLinks", () => {
  it("should pass with internal and external links", () => {
    const doc = createDoc(
      '<html><body><a href="/about">About</a><a href="https://google.com">Google</a></body></html>',
      "https://example.com",
    );
    const result = checkLinks(doc);
    expect(result.status).toBe("pass");
    expect(result.score).toBeGreaterThanOrEqual(80);
    expect((result.details as any).internalLinks).toBe(1);
    expect((result.details as any).externalLinks).toBe(1);
  });

  it("should warn when no links found", () => {
    const doc = createDoc("<html><body><p>No links</p></body></html>");
    const result = checkLinks(doc);
    expect(result.status).toBe("warning");
    expect(result.score).toBe(50);
  });

  it("should warn when no internal links", () => {
    const doc = createDoc(
      '<html><body><a href="https://google.com">External Only</a></body></html>',
      "https://example.com",
    );
    const result = checkLinks(doc);
    expect(result.score).toBeLessThanOrEqual(60);
  });
});

describe("checkSocialMeta", () => {
  it("should pass with complete OG and Twitter tags", () => {
    const doc = createDoc(`
      <html><head>
        <meta property="og:title" content="Title">
        <meta property="og:description" content="Desc">
        <meta property="og:image" content="https://example.com/img.jpg">
        <meta property="og:type" content="website">
        <meta property="og:url" content="https://example.com">
        <meta name="twitter:card" content="summary_large_image">
        <meta name="twitter:title" content="Title">
        <meta name="twitter:description" content="Desc">
        <meta name="twitter:image" content="https://example.com/img.jpg">
      </head></html>
    `);
    const result = checkSocialMeta(doc);
    expect(result.status).toBe("pass");
    expect(result.score).toBe(100);
  });

  it("should fail when no social meta tags present", () => {
    const doc = createDoc("<html><head></head></html>");
    const result = checkSocialMeta(doc);
    expect(result.status).toBe("fail");
    expect(result.score).toBe(0);
    expect(result.issues[0].severity).toBe("critical");
  });

  it("should give partial score for partial OG tags", () => {
    const doc = createDoc(`
      <html><head>
        <meta property="og:title" content="Title">
        <meta property="og:description" content="Desc">
      </head></html>
    `);
    const result = checkSocialMeta(doc);
    expect(result.score).toBeGreaterThan(0);
    expect(result.score).toBeLessThan(100);
  });
});

describe("analyzePage", () => {
  it("should produce an overall analysis with all 6 checks", () => {
    const doc = createDoc(`
      <html>
      <head>
        <title>Best Running Shoes for Marathon Training</title>
        <meta name="description" content="${"Great selection of marathon running shoes with expert reviews and buying guides for all levels of runners.".padEnd(140, ".")}">
        <meta property="og:title" content="Best Running Shoes">
        <meta property="og:description" content="Marathon shoes guide">
        <meta property="og:image" content="https://example.com/shoes.jpg">
        <meta property="og:type" content="website">
        <meta property="og:url" content="https://example.com/shoes">
        <meta name="twitter:card" content="summary_large_image">
        <meta name="twitter:title" content="Best Running Shoes">
        <meta name="twitter:description" content="Marathon shoes guide">
        <meta name="twitter:image" content="https://example.com/shoes.jpg">
      </head>
      <body>
        <h1>Best Running Shoes for Marathon Training</h1>
        <h2>Top Picks</h2>
        <img src="shoe1.jpg" alt="Nike Vaporfly running shoe">
        <img src="shoe2.jpg" alt="Adidas Adios Pro racing flat">
        <a href="/reviews">Reviews</a>
        <a href="https://nike.com">Nike</a>
      </body>
      </html>
    `);
    const result = analyzePage(doc);

    expect(result.checks).toHaveLength(6);
    expect(result.overallScore).toBeGreaterThanOrEqual(0);
    expect(result.overallScore).toBeLessThanOrEqual(100);
    expect(["red", "yellow", "green"]).toContain(result.scoreColor);
    expect(result.timestamp).toBeGreaterThan(0);
  });

  it("should return high score for well-optimized page", () => {
    const doc = createDoc(`
      <html>
      <head>
        <title>Best Running Shoes for Marathon Training</title>
        <meta name="description" content="${"A".repeat(140)}">
        <meta property="og:title" content="Best Running Shoes">
        <meta property="og:description" content="Guide">
        <meta property="og:image" content="https://example.com/img.jpg">
        <meta property="og:type" content="website">
        <meta property="og:url" content="https://example.com">
        <meta name="twitter:card" content="summary">
        <meta name="twitter:title" content="Best Running Shoes">
        <meta name="twitter:description" content="Guide">
        <meta name="twitter:image" content="https://example.com/img.jpg">
      </head>
      <body>
        <h1>Main Heading</h1>
        <h2>Sub Heading</h2>
        <img src="a.jpg" alt="Descriptive alt text">
        <a href="/internal">Internal</a>
        <a href="https://external.com">External</a>
      </body>
      </html>
    `);
    const result = analyzePage(doc);
    expect(result.overallScore).toBeGreaterThanOrEqual(80);
    expect(result.scoreColor).toBe("green");
  });

  it("should return low score for poorly optimized page", () => {
    const doc = createDoc("<html><head></head><body><p>Empty page</p></body></html>");
    const result = analyzePage(doc);
    expect(result.overallScore).toBeLessThan(50);
    expect(result.scoreColor).toBe("red");
  });

  it("should include URL and title in results", () => {
    const doc = createDoc(
      "<html><head><title>Test Page</title></head></html>",
      "https://example.com/test",
    );
    const result = analyzePage(doc);
    expect(result.url).toBe("https://example.com/test");
    expect(result.title).toBe("Test Page");
  });
});

// ---------------------------------------------------------------------------
// Realistic page simulations
// ---------------------------------------------------------------------------

describe("Real-world page simulations", () => {
  it("should analyze a news article page", () => {
    const doc = createDoc(`
      <html>
      <head>
        <title>Breaking: Major Climate Agreement Reached at UN Summit</title>
        <meta name="description" content="World leaders have agreed to a landmark climate deal at the UN Climate Summit, pledging to reduce emissions by 50% by 2030. The agreement includes binding commitments from all major economies.">
        <meta property="og:title" content="Major Climate Agreement Reached">
        <meta property="og:description" content="World leaders agree to landmark climate deal">
        <meta property="og:image" content="https://news.example.com/climate.jpg">
        <meta name="twitter:card" content="summary_large_image">
      </head>
      <body>
        <h1>Breaking: Major Climate Agreement Reached at UN Summit</h1>
        <h2>Key Points</h2>
        <h2>World Leaders React</h2>
        <h3>US President Statement</h3>
        <h3>EU Response</h3>
        <img src="summit.jpg" alt="World leaders at the UN Climate Summit">
        <img src="chart.jpg" alt="Emissions reduction targets chart">
        <a href="/politics">Politics</a>
        <a href="/climate">Climate</a>
        <a href="https://un.org">United Nations</a>
      </body>
      </html>
    `);
    const result = analyzePage(doc);
    expect(result.overallScore).toBeGreaterThanOrEqual(60);
    expect(result.checks.find((c) => c.id === "meta-title")?.status).toBe("pass");
    expect(result.checks.find((c) => c.id === "headings")?.status).toBe("pass");
  });

  it("should analyze an e-commerce product page", () => {
    const doc = createDoc(`
      <html>
      <head>
        <title>Nike Air Max 90 - Men's Running Shoes | ShoeStore</title>
        <meta name="description" content="Buy Nike Air Max 90 men's running shoes. Classic design with modern comfort. Air cushioning, rubber outsole. Available in 12 colors. Free shipping on orders over $75. Shop now!">
        <meta property="og:title" content="Nike Air Max 90">
        <meta property="og:description" content="Classic running shoes">
        <meta property="og:image" content="https://store.example.com/airmax90.jpg">
        <meta property="og:type" content="product">
        <meta property="og:url" content="https://store.example.com/nike-air-max-90">
        <meta name="twitter:card" content="summary_large_image">
        <meta name="twitter:title" content="Nike Air Max 90">
        <meta name="twitter:description" content="Classic running shoes">
        <meta name="twitter:image" content="https://store.example.com/airmax90.jpg">
      </head>
      <body>
        <h1>Nike Air Max 90 - Men's Running Shoes</h1>
        <h2>Product Details</h2>
        <h2>Customer Reviews</h2>
        <h3>Size Guide</h3>
        <img src="main.jpg" alt="Nike Air Max 90 side view">
        <img src="top.jpg" alt="Nike Air Max 90 top view">
        <img src="sole.jpg" alt="Nike Air Max 90 sole detail">
        <img src="box.jpg" alt="Nike Air Max 90 packaging">
        <a href="/shoes">All Shoes</a>
        <a href="/nike">Nike</a>
        <a href="/cart">Cart</a>
        <a href="https://nike.com">Official Nike</a>
      </body>
      </html>
    `);
    const result = analyzePage(doc);
    expect(result.overallScore).toBeGreaterThanOrEqual(80);
    expect(result.scoreColor).toBe("green");
  });

  it("should analyze a bare-bones blog page", () => {
    const doc = createDoc(`
      <html>
      <head>
        <title>My Blog</title>
      </head>
      <body>
        <h2>Latest Post</h2>
        <p>Some content here</p>
        <img src="photo.jpg">
      </body>
      </html>
    `);
    const result = analyzePage(doc);
    // Should have issues: generic title, no description, no H1, missing alt, no social meta
    expect(result.overallScore).toBeLessThan(50);
    expect(result.scoreColor).toBe("red");
    expect(
      result.checks.find((c) => c.id === "meta-description")?.issues.length,
    ).toBeGreaterThan(0);
  });
});
