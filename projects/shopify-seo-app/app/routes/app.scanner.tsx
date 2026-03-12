import type { ActionFunctionArgs, LoaderFunctionArgs } from "@remix-run/node";
import { json } from "@remix-run/node";
import {
  Page,
  Layout,
  Text,
  Card,
  BlockStack,
  InlineStack,
  Button,
  Badge,
  Box,
  Banner,
  Checkbox,
  Divider,
  IndexTable,
  useIndexResourceState,
  Filters,
  ChoiceList,
  Tooltip,
} from "@shopify/polaris";
import { TitleBar } from "@shopify/app-bridge-react";
import { useState, useCallback } from "react";
import { useLoaderData, useFetcher } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import { runScan, getLatestScanSummary, type ScanSummary } from "../services/seo-scanner.server";
import { getScanLimit } from "../services/billing.server";
import type { SeoCheckResult } from "../services/seo-rules.server";

// ---------------------------------------------------------------------------
// Loader: fetch latest scan results from DB
// ---------------------------------------------------------------------------
export const loader = async ({ request }: LoaderFunctionArgs) => {
  const { session } = await authenticate.admin(request);
  const summary = await getLatestScanSummary(session.shop);
  return json({ summary });
};

// ---------------------------------------------------------------------------
// Action: trigger a new scan
// ---------------------------------------------------------------------------
export const action = async ({ request }: ActionFunctionArgs) => {
  const { session } = await authenticate.admin(request);
  const formData = await request.formData();

  // Get scan limit from subscription plan
  const scanLimit = await getScanLimit(session.shop);

  const options = {
    products: formData.get("products") === "true",
    collections: formData.get("collections") === "true",
    pages: formData.get("pages") === "true",
    scanLimit,
  };

  // Use mock data (admin=null) until Shopify Partner account is ready
  const summary = await runScan(null, session.shop, options);

  return json({ summary });
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function Scanner() {
  const { summary: initialSummary } = useLoaderData<typeof loader>();
  const fetcher = useFetcher<{ summary: ScanSummary }>();

  const summary = fetcher.data?.summary || initialSummary;
  const isScanning = fetcher.state === "submitting";

  const [scanOptions, setScanOptions] = useState({
    products: true,
    collections: true,
    pages: true,
  });

  // Filtering state
  const [typeFilter, setTypeFilter] = useState<string[]>([]);
  const [scoreFilter, setScoreFilter] = useState<string[]>([]);
  const [sortColumn, setSortColumn] = useState<"score" | "issues">("score");
  const [sortDirection, setSortDirection] = useState<"ascending" | "descending">("ascending");

  const handleScan = () => {
    const formData = new FormData();
    formData.set("products", scanOptions.products.toString());
    formData.set("collections", scanOptions.collections.toString());
    formData.set("pages", scanOptions.pages.toString());
    fetcher.submit(formData, { method: "POST" });
  };

  // Filter & sort results
  const filteredResults = getFilteredResults(
    summary?.results || [],
    typeFilter,
    scoreFilter,
    sortColumn,
    sortDirection,
  );

  const resourceIDResolver = (result: SeoCheckResult) => result.resourceId;
  const { selectedResources, allResourcesSelected, handleSelectionChange } =
    useIndexResourceState(filteredResults, { resourceIDResolver });

  const handleSort = useCallback(
    (index: number, direction: "ascending" | "descending") => {
      const columns: ("score" | "issues")[] = ["score", "score", "issues", "score"];
      if (columns[index]) {
        setSortColumn(columns[index]);
        setSortDirection(direction);
      }
    },
    [],
  );

  return (
    <Page
      backAction={{ content: "Dashboard", url: "/app" }}
      title="SEO Scanner"
      subtitle="Scan your store for SEO issues and get actionable recommendations"
    >
      <TitleBar title="SEO Scanner" />
      <BlockStack gap="500">
        {/* Scan Configuration */}
        <Layout>
          <Layout.Section>
            <Card>
              <BlockStack gap="400">
                <Text as="h2" variant="headingMd">
                  Scan Configuration
                </Text>
                <Text as="p" variant="bodyMd" tone="subdued">
                  Select what to scan. The scanner checks meta titles,
                  descriptions, image alt text, URL slugs, and more.
                </Text>
                <Divider />
                <BlockStack gap="200">
                  <Checkbox
                    label="Products"
                    helpText="Scan all product pages for SEO issues"
                    checked={scanOptions.products}
                    onChange={(checked) =>
                      setScanOptions({ ...scanOptions, products: checked })
                    }
                  />
                  <Checkbox
                    label="Collections"
                    helpText="Scan collection pages for SEO optimization"
                    checked={scanOptions.collections}
                    onChange={(checked) =>
                      setScanOptions({ ...scanOptions, collections: checked })
                    }
                  />
                  <Checkbox
                    label="Pages"
                    helpText="Scan custom pages (About, Contact, etc.)"
                    checked={scanOptions.pages}
                    onChange={(checked) =>
                      setScanOptions({ ...scanOptions, pages: checked })
                    }
                  />
                </BlockStack>
                <Divider />
                <InlineStack align="space-between" blockAlign="center">
                  <Text as="p" variant="bodySm" tone="subdued">
                    {summary
                      ? `Last scan: ${new Date(summary.scannedAt).toLocaleString()}`
                      : "No previous scans"}
                  </Text>
                  <Button
                    variant="primary"
                    size="large"
                    loading={isScanning}
                    onClick={handleScan}
                  >
                    {isScanning ? "Scanning..." : "Start Scan"}
                  </Button>
                </InlineStack>
              </BlockStack>
            </Card>
          </Layout.Section>
        </Layout>

        {/* Scan Results Summary */}
        {summary && (
          <>
            <Layout>
              <Layout.Section variant="oneThird">
                <Card>
                  <BlockStack gap="200">
                    <Text as="h3" variant="headingMd">
                      Overall Score
                    </Text>
                    <InlineStack align="center">
                      <Text
                        as="p"
                        variant="heading2xl"
                        fontWeight="bold"
                        tone={getScoreTone(summary.overallScore)}
                      >
                        {summary.overallScore}
                      </Text>
                      <Text as="p" variant="bodyMd" tone="subdued">
                        / 100
                      </Text>
                    </InlineStack>
                  </BlockStack>
                </Card>
              </Layout.Section>
              <Layout.Section variant="oneThird">
                <Card>
                  <BlockStack gap="200">
                    <Text as="h3" variant="headingMd">
                      Resources Scanned
                    </Text>
                    <Text as="p" variant="heading2xl" fontWeight="bold">
                      {summary.totalResources}
                    </Text>
                  </BlockStack>
                </Card>
              </Layout.Section>
              <Layout.Section variant="oneThird">
                <Card>
                  <BlockStack gap="200">
                    <Text as="h3" variant="headingMd">
                      Issues Found
                    </Text>
                    <Text
                      as="p"
                      variant="heading2xl"
                      fontWeight="bold"
                      tone={summary.totalIssues > 0 ? "caution" : "success"}
                    >
                      {summary.totalIssues}
                    </Text>
                  </BlockStack>
                </Card>
              </Layout.Section>
            </Layout>

            {/* Score Distribution */}
            <Layout>
              <Layout.Section>
                <Card>
                  <BlockStack gap="300">
                    <Text as="h2" variant="headingMd">
                      Score Distribution
                    </Text>
                    <InlineStack gap="400">
                      <Badge tone="success">
                        Excellent (80-100): {summary.scoreDistribution.excellent}
                      </Badge>
                      <Badge tone="info">
                        Good (60-79): {summary.scoreDistribution.good}
                      </Badge>
                      <Badge tone="warning">
                        Needs Work (40-59): {summary.scoreDistribution.needsWork}
                      </Badge>
                      <Badge tone="critical">
                        Poor (0-39): {summary.scoreDistribution.poor}
                      </Badge>
                    </InlineStack>
                  </BlockStack>
                </Card>
              </Layout.Section>
            </Layout>

            {/* Top Issues */}
            {Object.keys(summary.issuesByType).length > 0 && (
              <Layout>
                <Layout.Section>
                  <Card>
                    <BlockStack gap="300">
                      <Text as="h2" variant="headingMd">
                        Top Issues
                      </Text>
                      <InlineStack gap="300" wrap>
                        {Object.entries(summary.issuesByType)
                          .sort(([, a], [, b]) => b - a)
                          .map(([ruleId, count]) => (
                            <Badge key={ruleId} tone="warning">
                              {formatRuleName(ruleId)}: {count}
                            </Badge>
                          ))}
                      </InlineStack>
                    </BlockStack>
                  </Card>
                </Layout.Section>
              </Layout>
            )}

            {/* Detailed Results Table */}
            <Layout>
              <Layout.Section>
                <Card padding="0">
                  <BlockStack gap="0">
                    <Box padding="400">
                      <InlineStack align="space-between" blockAlign="center">
                        <Text as="h2" variant="headingMd">
                          Detailed Results ({filteredResults.length})
                        </Text>
                        <InlineStack gap="200">
                          <ChoiceList
                            title=""
                            titleHidden
                            allowMultiple
                            choices={[
                              { label: "Products", value: "product" },
                              { label: "Collections", value: "collection" },
                              { label: "Pages", value: "page" },
                            ]}
                            selected={typeFilter}
                            onChange={setTypeFilter}
                          />
                        </InlineStack>
                      </InlineStack>
                    </Box>
                    <IndexTable
                      resourceName={{ singular: "resource", plural: "resources" }}
                      itemCount={filteredResults.length}
                      selectedItemsCount={
                        allResourcesSelected ? "All" : selectedResources.length
                      }
                      onSelectionChange={handleSelectionChange}
                      headings={[
                        { title: "Resource" },
                        { title: "Type" },
                        { title: "Score" },
                        { title: "Issues" },
                        { title: "Details" },
                      ]}
                      sortable={[false, false, true, true, false]}
                      sortDirection={sortDirection}
                      sortColumnIndex={sortColumn === "score" ? 2 : 3}
                      onSort={handleSort}
                    >
                      {filteredResults.map((result, index) => (
                        <IndexTable.Row
                          id={result.resourceId}
                          key={result.resourceId}
                          position={index}
                          selected={selectedResources.includes(result.resourceId)}
                        >
                          <IndexTable.Cell>
                            <Text as="span" variant="bodyMd" fontWeight="semibold">
                              {result.resourceTitle}
                            </Text>
                          </IndexTable.Cell>
                          <IndexTable.Cell>
                            <Badge>
                              {result.resourceType}
                            </Badge>
                          </IndexTable.Cell>
                          <IndexTable.Cell>
                            <Badge
                              tone={getScoreBadgeTone(result.seoScore)}
                            >
                              {result.seoScore}
                            </Badge>
                          </IndexTable.Cell>
                          <IndexTable.Cell>
                            {result.issues.length > 0 ? (
                              <Badge tone="warning">
                                {result.issues.length}
                              </Badge>
                            ) : (
                              <Badge tone="success">0</Badge>
                            )}
                          </IndexTable.Cell>
                          <IndexTable.Cell>
                            <Tooltip
                              content={result.issues.length > 0
                                ? result.issues.map((i) => `[${i.severity}] ${i.message}`).join("\n")
                                : "No issues found"
                              }
                            >
                              <Text as="span" variant="bodySm" tone="subdued">
                                {result.issues.length > 0
                                  ? result.issues.map((i) => i.ruleName).filter((v, i, a) => a.indexOf(v) === i).join(", ")
                                  : "All checks passed"}
                              </Text>
                            </Tooltip>
                          </IndexTable.Cell>
                        </IndexTable.Row>
                      ))}
                    </IndexTable>
                  </BlockStack>
                </Card>
              </Layout.Section>
            </Layout>
          </>
        )}

        {/* Empty State */}
        {!summary && !isScanning && (
          <Layout>
            <Layout.Section>
              <Card>
                <Box padding="800">
                  <BlockStack align="center" inlineAlign="center" gap="200">
                    <Text as="p" variant="headingMd" tone="subdued">
                      No scan results yet
                    </Text>
                    <Text as="p" variant="bodySm" tone="subdued">
                      Click "Start Scan" to analyze your store's SEO health.
                    </Text>
                  </BlockStack>
                </Box>
              </Card>
            </Layout.Section>
          </Layout>
        )}

        {/* What We Check */}
        <Layout>
          <Layout.Section>
            <Card>
              <BlockStack gap="300">
                <Text as="h2" variant="headingMd">
                  What We Check
                </Text>
                <InlineStack gap="300" wrap>
                  <Badge tone="info">Meta Title (30-60 chars)</Badge>
                  <Badge tone="info">Meta Description (120-160 chars)</Badge>
                  <Badge tone="info">Image Alt Text</Badge>
                  <Badge tone="info">H1 Tag Presence</Badge>
                  <Badge tone="info">URL Slug Quality</Badge>
                  <Badge tone="info">Duplicate Content</Badge>
                </InlineStack>
              </BlockStack>
            </Card>
          </Layout.Section>
        </Layout>
      </BlockStack>
    </Page>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getFilteredResults(
  results: SeoCheckResult[],
  typeFilter: string[],
  scoreFilter: string[],
  sortColumn: "score" | "issues",
  sortDirection: "ascending" | "descending",
): SeoCheckResult[] {
  let filtered = [...results];

  if (typeFilter.length > 0) {
    filtered = filtered.filter((r) => typeFilter.includes(r.resourceType));
  }

  filtered.sort((a, b) => {
    const mul = sortDirection === "ascending" ? 1 : -1;
    if (sortColumn === "score") return (a.seoScore - b.seoScore) * mul;
    return (a.issues.length - b.issues.length) * mul;
  });

  return filtered;
}

function getScoreTone(score: number): "success" | "caution" | "critical" | undefined {
  if (score >= 80) return "success";
  if (score >= 60) return "caution";
  return "critical";
}

function getScoreBadgeTone(score: number): "success" | "info" | "warning" | "critical" {
  if (score >= 80) return "success";
  if (score >= 60) return "info";
  if (score >= 40) return "warning";
  return "critical";
}

function formatRuleName(ruleId: string): string {
  const names: Record<string, string> = {
    "meta-title-length": "Meta Title",
    "meta-description-length": "Meta Description",
    "image-alt-text": "Image Alt Text",
    "h1-tag-presence": "H1 Tag",
    "url-slug-optimization": "URL Slug",
    "duplicate-content": "Duplicate Content",
  };
  return names[ruleId] || ruleId;
}
