# Chrome Web Store Listing

## Extension Name
SEOPilot Lite — SEO Analyzer

## Short Description (132 chars max)
One-click SEO analysis for any webpage. Get a 0-100 score, find issues, and see fix suggestions — free, fast, no account needed.

## Detailed Description

### Instantly Analyze Any Webpage's SEO Health

SEOPilot Lite is a free, privacy-first SEO analysis tool. Click the icon on any webpage and get a comprehensive SEO report in under 1 second — no account, no signup, no data collection.

### What You Get

**SEO Score (0-100)**
Every page gets a weighted score with clear color coding: Green (80-100) = Good, Yellow (50-79) = Needs Work, Red (0-49) = Poor.

**6 Comprehensive Checks**

1. **Meta Title Analysis** — Length check (30-60 chars optimal), generic title detection, keyword presence
2. **Meta Description** — Length check (120-160 chars optimal), missing description alerts
3. **Heading Structure** — H1 uniqueness, H1-H6 hierarchy validation, level skip detection
4. **Image Alt Text** — Coverage ratio, missing alt detection, low-quality alt flagging (e.g., "image", "photo")
5. **Link Analysis** — Internal vs. external links, empty href detection, nofollow ratio
6. **Open Graph & Twitter Card** — Social sharing tag completeness for Facebook, Twitter/X

**Social Media Previews**
See exactly how your page will look when shared on Google Search, Twitter/X, and Facebook — before you post.

**Export Report**
Copy your SEO report to clipboard in Markdown format, or download a beautifully formatted HTML report. Share with your team via docs, Notion, Slack, or email.

**Customizable Checks**
Toggle individual checks on/off based on what matters to you. Your settings are saved automatically.

### Why SEOPilot Lite?

- **100% Free** — No premium upsell, no feature gates
- **100% Private** — Zero data collection, zero external API calls. All analysis runs in your browser
- **Blazing Fast** — Analysis completes in under 1 second
- **No Account Needed** — Install and use immediately, no signup required
- **Lightweight** — Under 60KB total, won't slow down your browser
- **Dark Mode** — Automatically follows your system theme
- **Actionable** — Every issue comes with a specific fix recommendation

### Who Is This For?

- **Website owners** checking their own site's SEO
- **Content writers** optimizing blog posts and articles
- **Developers** validating meta tags and heading structure
- **SEO consultants** doing quick audits
- **Anyone** curious about a webpage's SEO health

### Permissions

SEOPilot Lite uses minimal permissions:
- **activeTab** — Only accesses the tab you're currently viewing when you click the icon
- **scripting** — Runs the analysis script on the current page
- **storage** — Saves your check toggle settings locally

We never access your browsing history, and we never send data anywhere.

---

*Made by the SEOPilot team. Want AI-powered SEO fixes for your Shopify store? Check out [SEOPilot for Shopify](https://apps.shopify.com/seopilot).*

## Category
Developer Tools

## Language
English

## Keywords
SEO, SEO checker, SEO analyzer, meta tags, meta title, meta description, heading structure, alt text, Open Graph, Twitter Card, page analysis, SEO audit, SEO score, free SEO tool, privacy

## Privacy Practices
- Does not collect user data
- Does not sell user data
- Does not use data for purposes unrelated to the extension's core functionality

## Promotional Screenshots

Three HTML mockup files are provided in `listing/`. Open each in Chrome at 1280x800 and capture:

1. **screenshot-1-score.html** — SEO Score Overview (shows the score ring and 6 checks)
2. **screenshot-2-issues.html** — Issue Details with Fix Suggestions (expanded check items)
3. **screenshot-3-preview.html** — Social Media Previews (Google SERP, Twitter, Facebook)

To capture at exact dimensions:
```bash
# Using Chrome DevTools (F12 → Device toolbar → 1280x800)
# Or using Playwright:
npx playwright screenshot --viewport-size=1280,800 listing/screenshot-1-score.html listing/screenshot-1.png
```
