/**
 * SEO Scanner Orchestrator
 *
 * Coordinates the full scan flow:
 *   1. Fetch resources from Shopify (or use mock data)
 *   2. Run SEO rules against each resource
 *   3. Check for cross-resource issues (duplicate content)
 *   4. Calculate overall store score
 *   5. Persist results to database
 */

import type { ShopifyProduct, ShopifyCollection, ShopifyPage } from "./shopify-graphql.server";
import { fetchProducts, fetchCollections, fetchPages } from "./shopify-graphql.server";
import {
  checkProduct,
  checkCollection,
  checkPage,
  checkDuplicateContent,
  type SeoCheckResult,
} from "./seo-rules.server";
import { getMockProducts, getMockCollections, getMockPages } from "./mock-data.server";
import db from "../db.server";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ScanOptions {
  products: boolean;
  collections: boolean;
  pages: boolean;
  scanLimit?: number; // max resources to scan (-1 or undefined = unlimited)
}

export interface ScanSummary {
  totalResources: number;
  totalIssues: number;
  overallScore: number;
  results: SeoCheckResult[];
  scannedAt: Date;
  issuesByType: Record<string, number>;
  scoreDistribution: {
    excellent: number; // 80-100
    good: number;      // 60-79
    needsWork: number;  // 40-59
    poor: number;       // 0-39
  };
}

// ---------------------------------------------------------------------------
// Scanner
// ---------------------------------------------------------------------------

/**
 * Run a full SEO scan.
 *
 * @param admin - Shopify admin GraphQL client (null to use mock data)
 * @param shop  - Shop domain
 * @param options - What resource types to scan
 */
export async function runScan(
  admin: { graphql: Function } | null,
  shop: string,
  options: ScanOptions,
): Promise<ScanSummary> {
  const allResults: SeoCheckResult[] = [];

  // 1. Fetch & check products (respect scan limit)
  if (options.products) {
    let products: ShopifyProduct[] = admin
      ? await fetchProducts(admin as any)
      : getMockProducts();

    // Apply scan limit if set (Free plan = 50 products)
    const limit = options.scanLimit;
    if (limit && limit > 0 && products.length > limit) {
      products = products.slice(0, limit);
    }

    for (const product of products) {
      allResults.push(checkProduct(product));
    }
  }

  // 2. Fetch & check collections
  if (options.collections) {
    const collections: ShopifyCollection[] = admin
      ? await fetchCollections(admin as any)
      : getMockCollections();

    for (const collection of collections) {
      allResults.push(checkCollection(collection));
    }
  }

  // 3. Fetch & check pages
  if (options.pages) {
    const pages: ShopifyPage[] = admin
      ? await fetchPages(admin as any)
      : getMockPages();

    for (const page of pages) {
      allResults.push(checkPage(page));
    }
  }

  // 4. Cross-resource checks (duplicate content)
  checkDuplicateContent(allResults);

  // 5. Calculate summary
  const totalIssues = allResults.reduce((sum, r) => sum + r.issues.length, 0);
  const overallScore = allResults.length > 0
    ? Math.round(allResults.reduce((sum, r) => sum + r.seoScore, 0) / allResults.length)
    : 100;

  const issuesByType: Record<string, number> = {};
  for (const result of allResults) {
    for (const issue of result.issues) {
      issuesByType[issue.ruleId] = (issuesByType[issue.ruleId] || 0) + 1;
    }
  }

  const scoreDistribution = {
    excellent: allResults.filter((r) => r.seoScore >= 80).length,
    good: allResults.filter((r) => r.seoScore >= 60 && r.seoScore < 80).length,
    needsWork: allResults.filter((r) => r.seoScore >= 40 && r.seoScore < 60).length,
    poor: allResults.filter((r) => r.seoScore < 40).length,
  };

  const scannedAt = new Date();

  // 6. Persist to database
  await persistScanResults(shop, allResults, scannedAt);

  return {
    totalResources: allResults.length,
    totalIssues,
    overallScore,
    results: allResults,
    scannedAt,
    issuesByType,
    scoreDistribution,
  };
}

/**
 * Persist scan results to the database.
 */
async function persistScanResults(
  shop: string,
  results: SeoCheckResult[],
  scannedAt: Date,
): Promise<void> {
  // Delete old results for this shop (keep only latest scan)
  await db.scanResult.deleteMany({ where: { shop } });

  // Insert new results
  if (results.length > 0) {
    await db.scanResult.createMany({
      data: results.map((r) => ({
        shop,
        resourceType: r.resourceType,
        resourceId: r.resourceId,
        resourceTitle: r.resourceTitle,
        seoScore: r.seoScore,
        issues: r.issues as any,
        metadata: r.metadata as any,
        scannedAt,
      })),
    });
  }
}

/**
 * Get the latest scan summary from the database.
 */
export async function getLatestScanSummary(
  shop: string,
): Promise<ScanSummary | null> {
  const results = await db.scanResult.findMany({
    where: { shop },
    orderBy: { scannedAt: "desc" },
  });

  if (results.length === 0) return null;

  // All results from the same scan have the same scannedAt
  const scannedAt = results[0].scannedAt;

  const checkResults: SeoCheckResult[] = results.map((r) => ({
    resourceType: r.resourceType as any,
    resourceId: r.resourceId,
    resourceTitle: r.resourceTitle,
    seoScore: r.seoScore,
    issues: r.issues as any[],
    metadata: r.metadata as any,
  }));

  const totalIssues = checkResults.reduce((sum, r) => sum + r.issues.length, 0);
  const overallScore = checkResults.length > 0
    ? Math.round(checkResults.reduce((sum, r) => sum + r.seoScore, 0) / checkResults.length)
    : 100;

  const issuesByType: Record<string, number> = {};
  for (const result of checkResults) {
    for (const issue of result.issues) {
      issuesByType[issue.ruleId] = (issuesByType[issue.ruleId] || 0) + 1;
    }
  }

  const scoreDistribution = {
    excellent: checkResults.filter((r) => r.seoScore >= 80).length,
    good: checkResults.filter((r) => r.seoScore >= 60 && r.seoScore < 80).length,
    needsWork: checkResults.filter((r) => r.seoScore >= 40 && r.seoScore < 60).length,
    poor: checkResults.filter((r) => r.seoScore < 40).length,
  };

  return {
    totalResources: checkResults.length,
    totalIssues,
    overallScore,
    results: checkResults,
    scannedAt,
    issuesByType,
    scoreDistribution,
  };
}
