import type { LoaderFunctionArgs } from "@remix-run/node";
import { json } from "@remix-run/node";
import {
  Page,
  Layout,
  Text,
  Card,
  BlockStack,
  InlineStack,
  Box,
  Badge,
  Divider,
  Button,
  ProgressBar,
} from "@shopify/polaris";
import { TitleBar } from "@shopify/app-bridge-react";
import { useLoaderData, useNavigate } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import { getLatestScanSummary, type ScanSummary } from "../services/seo-scanner.server";
import { getSubscriptionInfo } from "../services/billing.server";

// ---------------------------------------------------------------------------
// Loader
// ---------------------------------------------------------------------------
export const loader = async ({ request }: LoaderFunctionArgs) => {
  const { session } = await authenticate.admin(request);
  const [summary, subscriptionInfo] = await Promise.all([
    getLatestScanSummary(session.shop),
    getSubscriptionInfo(session.shop),
  ]);
  return json({
    summary,
    subscription: {
      plan: subscriptionInfo.plan,
      planName: subscriptionInfo.planConfig.name,
      aiCreditsUsed: subscriptionInfo.aiCreditsUsed,
      aiCreditsLimit: subscriptionInfo.aiCreditsLimit,
      isUnlimited: subscriptionInfo.isUnlimited,
      canUseAI: subscriptionInfo.canUseAI,
      usagePercent: subscriptionInfo.usagePercent,
    },
  });
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function Dashboard() {
  const { summary, subscription } = useLoaderData<typeof loader>();
  const navigate = useNavigate();

  return (
    <Page>
      <TitleBar title="SEOPilot Dashboard" />
      <BlockStack gap="500">
        {/* SEO Health Score */}
        <Layout>
          <Layout.Section>
            <Card>
              <BlockStack gap="400">
                <Text as="h2" variant="headingLg">
                  SEO Health Score
                </Text>
                {summary ? (
                  <InlineStack gap="800" blockAlign="center">
                    <Box minWidth="140px">
                      <BlockStack align="center" inlineAlign="center" gap="100">
                        <Text
                          as="p"
                          variant="heading3xl"
                          fontWeight="bold"
                          tone={getScoreTone(summary.overallScore)}
                        >
                          {summary.overallScore}
                        </Text>
                        <Text as="p" variant="bodySm" tone="subdued">
                          / 100
                        </Text>
                        <Box width="120px">
                          <ProgressBar
                            progress={summary.overallScore}
                            tone={summary.overallScore >= 70 ? "success" : summary.overallScore >= 50 ? "highlight" : "critical"}
                            size="small"
                          />
                        </Box>
                      </BlockStack>
                    </Box>
                    <Divider />
                    <BlockStack gap="300">
                      <Text as="p" variant="bodyMd">
                        {getScoreMessage(summary.overallScore)}
                      </Text>
                      <Text as="p" variant="bodySm" tone="subdued">
                        Last scanned: {new Date(summary.scannedAt).toLocaleString()}
                      </Text>
                      <InlineStack gap="200">
                        <Button onClick={() => navigate("/app/scanner")}>
                          Rescan
                        </Button>
                        {summary.totalIssues > 0 && (
                          <Button
                            variant="primary"
                            onClick={() => navigate("/app/fixer")}
                          >
                            Fix {summary.totalIssues} Issues
                          </Button>
                        )}
                      </InlineStack>
                    </BlockStack>
                  </InlineStack>
                ) : (
                  <InlineStack gap="800" blockAlign="center">
                    <Box minWidth="140px">
                      <BlockStack align="center" inlineAlign="center">
                        <Text as="p" variant="heading3xl" fontWeight="bold" tone="subdued">
                          --
                        </Text>
                        <Text as="p" variant="bodySm" tone="subdued">
                          / 100
                        </Text>
                      </BlockStack>
                    </Box>
                    <BlockStack gap="300">
                      <Text as="p" variant="bodyMd" tone="subdued">
                        Run your first scan to see your SEO health score.
                      </Text>
                      <Button
                        variant="primary"
                        onClick={() => navigate("/app/scanner")}
                      >
                        Start First Scan
                      </Button>
                    </BlockStack>
                  </InlineStack>
                )}
              </BlockStack>
            </Card>
          </Layout.Section>
        </Layout>

        {/* Quick Stats */}
        <Layout>
          <Layout.Section variant="oneThird">
            <Card>
              <BlockStack gap="200">
                <InlineStack align="space-between">
                  <Text as="h3" variant="headingMd">
                    Resources Scanned
                  </Text>
                  <Badge tone="info">
                    {summary?.totalResources ?? 0}
                  </Badge>
                </InlineStack>
                <Divider />
                {summary ? (
                  <InlineStack gap="200" wrap>
                    <Badge>
                      Products: {summary.results.filter((r) => r.resourceType === "product").length}
                    </Badge>
                    <Badge>
                      Collections: {summary.results.filter((r) => r.resourceType === "collection").length}
                    </Badge>
                    <Badge>
                      Pages: {summary.results.filter((r) => r.resourceType === "page").length}
                    </Badge>
                  </InlineStack>
                ) : (
                  <Text as="p" variant="bodySm" tone="subdued">
                    No products scanned yet
                  </Text>
                )}
              </BlockStack>
            </Card>
          </Layout.Section>
          <Layout.Section variant="oneThird">
            <Card>
              <BlockStack gap="200">
                <InlineStack align="space-between">
                  <Text as="h3" variant="headingMd">
                    Issues Found
                  </Text>
                  <Badge tone={summary && summary.totalIssues > 0 ? "warning" : "success"}>
                    {summary?.totalIssues ?? 0}
                  </Badge>
                </InlineStack>
                <Divider />
                {summary && summary.totalIssues > 0 ? (
                  <BlockStack gap="100">
                    {Object.entries(summary.issuesByType)
                      .sort(([, a], [, b]) => b - a)
                      .slice(0, 3)
                      .map(([ruleId, count]) => (
                        <InlineStack key={ruleId} align="space-between">
                          <Text as="span" variant="bodySm">
                            {formatRuleName(ruleId)}
                          </Text>
                          <Badge tone="warning">{count}</Badge>
                        </InlineStack>
                      ))}
                  </BlockStack>
                ) : (
                  <Text as="p" variant="bodySm" tone="subdued">
                    {summary ? "No issues found!" : "Run a scan to detect issues"}
                  </Text>
                )}
              </BlockStack>
            </Card>
          </Layout.Section>
          <Layout.Section variant="oneThird">
            <Card>
              <BlockStack gap="200">
                <InlineStack align="space-between">
                  <Text as="h3" variant="headingMd">
                    Score Breakdown
                  </Text>
                </InlineStack>
                <Divider />
                {summary ? (
                  <BlockStack gap="100">
                    <InlineStack align="space-between">
                      <Text as="span" variant="bodySm">Excellent (80+)</Text>
                      <Badge tone="success">{summary.scoreDistribution.excellent}</Badge>
                    </InlineStack>
                    <InlineStack align="space-between">
                      <Text as="span" variant="bodySm">Good (60-79)</Text>
                      <Badge tone="info">{summary.scoreDistribution.good}</Badge>
                    </InlineStack>
                    <InlineStack align="space-between">
                      <Text as="span" variant="bodySm">Needs Work (40-59)</Text>
                      <Badge tone="warning">{summary.scoreDistribution.needsWork}</Badge>
                    </InlineStack>
                    <InlineStack align="space-between">
                      <Text as="span" variant="bodySm">Poor (&lt;40)</Text>
                      <Badge tone="critical">{summary.scoreDistribution.poor}</Badge>
                    </InlineStack>
                  </BlockStack>
                ) : (
                  <Text as="p" variant="bodySm" tone="subdued">
                    No data yet
                  </Text>
                )}
              </BlockStack>
            </Card>
          </Layout.Section>
        </Layout>

        {/* Recent Scan Results */}
        <Layout>
          <Layout.Section>
            <Card>
              <BlockStack gap="300">
                <InlineStack align="space-between">
                  <Text as="h2" variant="headingMd">
                    {summary ? "Recent Scan Results" : "Recent Activity"}
                  </Text>
                  {summary && (
                    <Button
                      variant="plain"
                      onClick={() => navigate("/app/scanner")}
                    >
                      View All
                    </Button>
                  )}
                </InlineStack>
                {summary ? (
                  <BlockStack gap="200">
                    {summary.results
                      .sort((a, b) => a.seoScore - b.seoScore)
                      .slice(0, 5)
                      .map((result) => (
                        <Box
                          key={result.resourceId}
                          padding="300"
                          background="bg-surface-secondary"
                          borderRadius="200"
                        >
                          <InlineStack align="space-between" blockAlign="center">
                            <BlockStack gap="100">
                              <InlineStack gap="200" blockAlign="center">
                                <Text as="span" variant="bodyMd" fontWeight="semibold">
                                  {result.resourceTitle}
                                </Text>
                                <Badge>{result.resourceType}</Badge>
                              </InlineStack>
                              <Text as="span" variant="bodySm" tone="subdued">
                                {result.issues.length > 0
                                  ? result.issues
                                      .map((i) => i.ruleName)
                                      .filter((v, i, a) => a.indexOf(v) === i)
                                      .join(", ")
                                  : "All checks passed"}
                              </Text>
                            </BlockStack>
                            <InlineStack gap="200" blockAlign="center">
                              {result.issues.length > 0 && (
                                <Badge tone="warning">
                                  {result.issues.length} issues
                                </Badge>
                              )}
                              <Badge tone={getScoreBadgeTone(result.seoScore)}>
                                Score: {result.seoScore}
                              </Badge>
                            </InlineStack>
                          </InlineStack>
                        </Box>
                      ))}
                    {summary.results.length > 5 && (
                      <Text as="p" variant="bodySm" tone="subdued">
                        Showing 5 lowest-scoring resources of {summary.results.length} total.
                      </Text>
                    )}
                  </BlockStack>
                ) : (
                  <Box
                    padding="400"
                    background="bg-surface-secondary"
                    borderRadius="200"
                  >
                    <BlockStack align="center" inlineAlign="center">
                      <Text as="p" variant="bodyMd" tone="subdued">
                        No recent activity. Start by scanning your store!
                      </Text>
                    </BlockStack>
                  </Box>
                )}
              </BlockStack>
            </Card>
          </Layout.Section>
        </Layout>

        {/* Plan & Credits */}
        <Layout>
          <Layout.Section>
            <Card>
              <BlockStack gap="300">
                <InlineStack align="space-between" blockAlign="center">
                  <Text as="h2" variant="headingMd">
                    Your Plan
                  </Text>
                  <Badge tone="success">{subscription.planName}</Badge>
                </InlineStack>
                <Divider />
                <InlineStack align="space-between">
                  <Text as="span" variant="bodyMd">AI Credits</Text>
                  <Text as="span" variant="bodyMd">
                    {subscription.isUnlimited
                      ? `${subscription.aiCreditsUsed} used (unlimited)`
                      : `${subscription.aiCreditsUsed} / ${subscription.aiCreditsLimit}`}
                  </Text>
                </InlineStack>
                {!subscription.isUnlimited && (
                  <ProgressBar
                    progress={subscription.usagePercent}
                    tone={subscription.usagePercent >= 90 ? "critical" : "success"}
                    size="small"
                  />
                )}
                {!subscription.canUseAI && (
                  <Button variant="primary" onClick={() => navigate("/app/settings")}>
                    Upgrade Plan
                  </Button>
                )}
              </BlockStack>
            </Card>
          </Layout.Section>
        </Layout>

        {/* Quick Actions */}
        <Layout>
          <Layout.Section>
            <Card>
              <BlockStack gap="400">
                <Text as="h2" variant="headingMd">
                  Quick Actions
                </Text>
                <InlineStack gap="400">
                  <Button onClick={() => navigate("/app/scanner")}>
                    {summary ? "Rescan Store" : "Scan Store SEO"}
                  </Button>
                  <Button onClick={() => navigate("/app/fixer")}>
                    View & Fix Issues
                  </Button>
                  <Button onClick={() => navigate("/app/settings")}>
                    Settings & Pricing
                  </Button>
                  <Button onClick={() => navigate("/app/help")}>
                    Help & FAQ
                  </Button>
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

function getScoreMessage(score: number): string {
  if (score >= 90) return "Excellent! Your store's SEO is in great shape.";
  if (score >= 80) return "Good job! A few minor improvements can make it even better.";
  if (score >= 60) return "Room for improvement. Fix the highlighted issues to boost your rankings.";
  if (score >= 40) return "Needs attention. Several SEO issues are affecting your search visibility.";
  return "Critical! Major SEO issues detected. Address them to improve search rankings.";
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
