/**
 * Shopify Real API Integration Tests
 *
 * Prerequisites:
 *   1. App must be installed on a dev store via `shopify app dev`
 *   2. A valid offline session must exist in the Session table
 *
 * These tests use the stored access token to make direct GraphQL calls
 * to the Shopify Admin API, verifying the full scan/fix pipeline works
 * against real store data.
 *
 * Run with: npx vitest run tests/shopify-integration.test.ts
 */

import { describe, it, expect, beforeAll } from "vitest";
import { PrismaClient } from "@prisma/client";
import { config } from "dotenv";
import { resolve } from "path";

// Load .env
config({ path: resolve(__dirname, "../.env") });

const DEV_STORE = "seopilot-test.myshopify.com";
const API_VERSION = "2025-01";

let prisma: PrismaClient;
let accessToken: string | null = null;

/**
 * Make a GraphQL request to the Shopify Admin API
 */
async function shopifyGraphQL(query: string, variables?: Record<string, unknown>) {
  if (!accessToken) throw new Error("No access token available");

  const response = await fetch(
    `https://${DEV_STORE}/admin/api/${API_VERSION}/graphql.json`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": accessToken,
      },
      body: JSON.stringify({ query, variables }),
    },
  );

  if (!response.ok) {
    throw new Error(`Shopify API error: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

// Check if we have a valid session
let hasSession = false;

beforeAll(async () => {
  prisma = new PrismaClient();

  // Look for an offline session for the dev store
  const session = await prisma.session.findFirst({
    where: {
      shop: DEV_STORE,
      isOnline: false,
    },
  });

  if (session?.accessToken) {
    accessToken = session.accessToken;
    hasSession = true;
    console.log(`Found offline session for ${DEV_STORE}`);
    console.log(`Access token: ${accessToken.substring(0, 12)}...`);
  } else {
    console.log(`No offline session found for ${DEV_STORE}`);
    console.log("Run 'npm run dev' and install the app on the dev store first.");
  }
});

const describeIf = () => (hasSession ? describe : describe.skip);

// We use a function because hasSession is set in beforeAll
describe("Shopify Real API Integration", () => {
  // ── Shop Info ──
  it("fetches shop info from the real API", async () => {
    if (!hasSession) {
      console.log("SKIPPED: No session. Install app on dev store first.");
      return;
    }

    const result = await shopifyGraphQL(`{
      shop {
        name
        url
        plan { displayName }
        currencyCode
      }
    }`);

    expect(result.data?.shop).toBeDefined();
    console.log(`Shop: ${result.data.shop.name}`);
    console.log(`URL: ${result.data.shop.url}`);
    console.log(`Plan: ${result.data.shop.plan.displayName}`);
    console.log(`Currency: ${result.data.shop.currencyCode}`);
  });

  // ── Products ──
  it("fetches products from the dev store", async () => {
    if (!hasSession) return;

    const result = await shopifyGraphQL(`{
      products(first: 10) {
        edges {
          node {
            id
            title
            handle
            description
            seo { title description }
            images(first: 5) {
              edges {
                node { url altText }
              }
            }
          }
        }
        pageInfo { hasNextPage }
      }
    }`);

    const products = result.data?.products?.edges || [];
    expect(products.length).toBeGreaterThan(0);

    console.log(`\nProducts found: ${products.length}`);
    for (const { node } of products) {
      const imgCount = node.images?.edges?.length || 0;
      const altMissing = node.images?.edges?.filter((e: any) => !e.node.altText).length || 0;
      console.log(`  - ${node.title} (SEO title: ${node.seo?.title || "(none)"}, images: ${imgCount}, alt missing: ${altMissing})`);
    }
  });

  // ── Collections ──
  it("fetches collections from the dev store", async () => {
    if (!hasSession) return;

    const result = await shopifyGraphQL(`{
      collections(first: 10) {
        edges {
          node {
            id
            title
            handle
            description
            seo { title description }
          }
        }
      }
    }`);

    const collections = result.data?.collections?.edges || [];
    console.log(`\nCollections found: ${collections.length}`);
    for (const { node } of collections) {
      console.log(`  - ${node.title} (SEO title: ${node.seo?.title || "(none)"})`);
    }
  });

  // ── Pages ──
  it("fetches pages from the dev store", async () => {
    if (!hasSession) return;

    const result = await shopifyGraphQL(`{
      pages(first: 10) {
        edges {
          node {
            id
            title
            handle
            body
            seo { title description }
          }
        }
      }
    }`);

    const pages = result.data?.pages?.edges || [];
    console.log(`\nPages found: ${pages.length}`);
    for (const { node } of pages) {
      console.log(`  - ${node.title} (SEO title: ${node.seo?.title || "(none)"}, body: ${node.body?.length || 0} chars)`);
    }
  });

  // ── Full Scan with Real Data ──
  it("runs a full scan using real Shopify data", async () => {
    if (!hasSession) return;

    // Import scanner
    const { runScan } = await import("../app/services/seo-scanner.server");

    // Create a mock admin client that wraps our direct API access
    const mockAdmin = {
      graphql: async (query: string, options?: { variables?: Record<string, unknown> }) => {
        const json = await shopifyGraphQL(query, options?.variables);
        return {
          json: async () => json,
        } as Response;
      },
    };

    const summary = await runScan(mockAdmin as any, DEV_STORE, {
      products: true,
      collections: true,
      pages: true,
    });

    expect(summary.totalResources).toBeGreaterThan(0);
    expect(summary.overallScore).toBeGreaterThanOrEqual(0);
    expect(summary.overallScore).toBeLessThanOrEqual(100);

    console.log("\n=== Real Store Scan Summary ===");
    console.log(`Total Resources: ${summary.totalResources}`);
    console.log(`Overall Score: ${summary.overallScore}/100`);
    console.log(`Total Issues: ${summary.totalIssues}`);
    console.log(`Score Distribution:`, summary.scoreDistribution);

    // Show top issues
    const issueEntries = Object.entries(summary.issuesByType).sort((a, b) => b[1] - a[1]);
    console.log("\nTop Issues:");
    for (const [type, count] of issueEntries.slice(0, 5)) {
      console.log(`  ${type}: ${count}`);
    }

    // Show resources needing most attention
    const worstResources = [...summary.results]
      .sort((a, b) => a.seoScore - b.seoScore)
      .slice(0, 5);
    console.log("\nResources needing attention:");
    for (const r of worstResources) {
      console.log(`  [${r.resourceType}] ${r.resourceTitle}: score=${r.seoScore}, issues=${r.issues.length}`);
    }
  });

  // ── AI Fix with Real Data ──
  it("generates AI fix for a real product", async () => {
    if (!hasSession) return;

    // Find a product with SEO issues
    const result = await shopifyGraphQL(`{
      products(first: 5) {
        edges {
          node {
            id
            title
            description
            seo { title description }
          }
        }
      }
    }`);

    const products = result.data?.products?.edges || [];
    if (products.length === 0) return;

    const product = products[0].node;
    const currentTitle = product.seo?.title || product.title;

    // Generate AI fix using real OpenAI
    const { generateFix } = await import("../app/services/ai-fixer.server");
    const fix = await generateFix({
      fixType: "meta_title",
      resourceTitle: product.title,
      resourceType: "product",
      currentValue: currentTitle,
      productDescription: product.description,
      tone: "professional",
    });

    console.log(`\nAI Fix for "${product.title}":`);
    console.log(`  Current: "${currentTitle}"`);
    console.log(`  Suggested: "${fix.suggestedValue}"`);
    console.log(`  Used AI: ${!fix.usedMock}`);
    console.log(`  Confidence: ${fix.confidence}`);

    expect(fix.suggestedValue).toBeDefined();
    expect(fix.suggestedValue.length).toBeGreaterThan(0);
  }, 15000);

  // ── Write Access Test (product SEO update) ──
  it("can update product SEO fields via mutation", async () => {
    if (!hasSession) return;

    // First get a product
    const result = await shopifyGraphQL(`{
      products(first: 1) {
        edges {
          node {
            id
            title
            seo { title description }
          }
        }
      }
    }`);

    const product = result.data?.products?.edges?.[0]?.node;
    if (!product) return;

    const originalSeoTitle = product.seo?.title || "";

    // Set a test SEO title
    const testTitle = `${product.title} | SEOPilot Test ${Date.now()}`;
    const mutationResult = await shopifyGraphQL(`
      mutation productUpdate($input: ProductInput!) {
        productUpdate(input: $input) {
          product {
            id
            seo { title description }
          }
          userErrors {
            field
            message
          }
        }
      }
    `, {
      input: {
        id: product.id,
        seo: { title: testTitle },
      },
    });

    const errors = mutationResult.data?.productUpdate?.userErrors || [];
    expect(errors).toHaveLength(0);

    const updatedSeo = mutationResult.data?.productUpdate?.product?.seo;
    expect(updatedSeo?.title).toBe(testTitle);

    console.log(`\nMutation test on "${product.title}":`);
    console.log(`  Set SEO title to: "${testTitle}"`);

    // Revert back to original
    await shopifyGraphQL(`
      mutation productUpdate($input: ProductInput!) {
        productUpdate(input: $input) {
          product { id }
          userErrors { field message }
        }
      }
    `, {
      input: {
        id: product.id,
        seo: { title: originalSeoTitle || null },
      },
    });

    console.log(`  Reverted SEO title to: "${originalSeoTitle || "(none)"}"`);
  });

  // ── Billing API Check ──
  it("can query app subscriptions", async () => {
    if (!hasSession) return;

    const result = await shopifyGraphQL(`{
      appInstallation {
        activeSubscriptions {
          name
          status
          lineItems {
            plan {
              pricingDetails {
                ... on AppRecurringPricing {
                  price { amount currencyCode }
                  interval
                }
              }
            }
          }
        }
      }
    }`);

    const subs = result.data?.appInstallation?.activeSubscriptions || [];
    console.log(`\nActive subscriptions: ${subs.length}`);
    for (const sub of subs) {
      console.log(`  - ${sub.name}: ${sub.status}`);
    }

    // No subscription is expected on free plan
    // This just verifies the query works without errors
    expect(result.errors).toBeUndefined();
  });
});
