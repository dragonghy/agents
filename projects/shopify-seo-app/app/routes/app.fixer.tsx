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
  Tabs,
  Divider,
  IndexTable,
  useIndexResourceState,
  Modal,
  Tooltip,
} from "@shopify/polaris";
import { TitleBar } from "@shopify/app-bridge-react";
import { useState, useCallback } from "react";
import { useLoaderData, useFetcher, useNavigate } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import { getLatestScanSummary } from "../services/seo-scanner.server";
import {
  generateFixWithCredits,
  generateFixesWithCredits,
  type FixRequest,
  type FixSuggestion,
} from "../services/ai-fixer.server";
import {
  createFixRecord,
  markFixApplied,
  revertFix,
  getFixHistory,
  getPendingFixesCount,
  getAppliedFixesCount,
  type FixRecord,
} from "../services/fix-history.server";
import { applyFixMock } from "../services/shopify-mutations.server";
import { getSubscriptionInfo } from "../services/billing.server";
import type { SeoCheckResult, SeoIssue } from "../services/seo-rules.server";
import db from "../db.server";

// ---------------------------------------------------------------------------
// Loader
// ---------------------------------------------------------------------------
export const loader = async ({ request }: LoaderFunctionArgs) => {
  const { session } = await authenticate.admin(request);
  const shop = session.shop;

  // Load user settings for AI tone
  const userSettings = await db.userSettings.findUnique({ where: { shop } });
  const aiTone = (userSettings?.aiTone as "professional" | "casual" | "luxury") || "professional";

  const [scanSummary, fixHistory, pendingCount, appliedCount, subscriptionInfo] = await Promise.all([
    getLatestScanSummary(shop),
    getFixHistory(shop, { limit: 50 }),
    getPendingFixesCount(shop),
    getAppliedFixesCount(shop),
    getSubscriptionInfo(shop),
  ]);

  // Extract fixable issues from scan results
  const fixableIssues = extractFixableIssues(scanSummary?.results || []);

  return json({
    fixableIssues,
    fixHistory,
    pendingCount,
    appliedCount,
    hasScanData: !!scanSummary,
    aiTone,
    subscription: {
      plan: subscriptionInfo.plan,
      aiCreditsUsed: subscriptionInfo.aiCreditsUsed,
      aiCreditsLimit: subscriptionInfo.aiCreditsLimit,
      aiCreditsRemaining: subscriptionInfo.isUnlimited ? -1 : (subscriptionInfo.aiCreditsLimit - subscriptionInfo.aiCreditsUsed),
      canUseAI: subscriptionInfo.canUseAI,
      isUnlimited: subscriptionInfo.isUnlimited,
      usagePercent: subscriptionInfo.usagePercent,
    },
  });
};

// ---------------------------------------------------------------------------
// Action
// ---------------------------------------------------------------------------
export const action = async ({ request }: ActionFunctionArgs) => {
  const { session } = await authenticate.admin(request);
  const shop = session.shop;
  const formData = await request.formData();
  const intent = formData.get("intent") as string;

  // Read user's AI tone preference
  const userSettings = await db.userSettings.findUnique({ where: { shop } });
  const aiTone = (userSettings?.aiTone as "professional" | "casual" | "luxury") || "professional";

  switch (intent) {
    case "generate": {
      // Generate AI fix suggestion for a single issue (with credit check)
      const fixType = formData.get("fixType") as FixRequest["fixType"];
      const resourceTitle = formData.get("resourceTitle") as string;
      const resourceType = formData.get("resourceType") as FixRequest["resourceType"];
      const currentValue = formData.get("currentValue") as string | null;
      const description = formData.get("description") as string;

      const result = await generateFixWithCredits(shop, {
        fixType,
        resourceTitle,
        resourceType,
        currentValue,
        productDescription: description,
        tone: aiTone,
      });

      if (result.error) {
        return json({
          intent: "generate",
          error: result.error,
          creditsRemaining: result.creditsRemaining,
        });
      }

      return json({
        intent: "generate",
        suggestion: result.suggestion,
        creditsRemaining: result.creditsRemaining,
      });
    }

    case "generate_batch": {
      // Generate fixes for multiple issues (with credit tracking)
      const issuesJson = formData.get("issues") as string;
      const issues: Array<{
        fixType: FixRequest["fixType"];
        resourceTitle: string;
        resourceType: FixRequest["resourceType"];
        resourceId: string;
        currentValue: string | null;
      }> = JSON.parse(issuesJson);

      const requests: FixRequest[] = issues.map((issue) => ({
        fixType: issue.fixType,
        resourceTitle: issue.resourceTitle,
        resourceType: issue.resourceType,
        currentValue: issue.currentValue,
        tone: aiTone,
      }));

      const batchResult = await generateFixesWithCredits(shop, requests);

      const suggestions = batchResult.suggestions.map((s, i) => ({
        ...s,
        resourceId: issues[i].resourceId,
        resourceTitle: issues[i].resourceTitle,
        resourceType: issues[i].resourceType,
      }));

      return json({
        intent: "generate_batch",
        suggestions,
        errors: batchResult.errors,
        creditsRemaining: batchResult.creditsRemaining,
        stoppedAtIndex: batchResult.stoppedAtIndex,
      });
    }

    case "apply": {
      // Apply a single fix (create record + mark applied)
      const resourceType = formData.get("resourceType") as string;
      const resourceId = formData.get("resourceId") as string;
      const resourceTitle = formData.get("resourceTitle") as string;
      const fixType = formData.get("fixType") as FixRequest["fixType"];
      const originalValue = formData.get("originalValue") as string | null;
      const fixedValue = formData.get("fixedValue") as string;

      // Create record and apply (mock mode — no real Shopify write)
      const record = await createFixRecord(
        shop, resourceType, resourceId, resourceTitle,
        fixType, originalValue, fixedValue,
      );
      await applyFixMock(); // Would use applyProductSeoFix etc. with real admin
      await markFixApplied(record.id);

      return json({ intent: "apply", success: true, fixId: record.id });
    }

    case "apply_batch": {
      // Apply multiple fixes
      const fixesJson = formData.get("fixes") as string;
      const fixes: Array<{
        resourceType: string;
        resourceId: string;
        resourceTitle: string;
        fixType: FixRequest["fixType"];
        originalValue: string | null;
        fixedValue: string;
      }> = JSON.parse(fixesJson);

      const appliedIds: string[] = [];
      for (const fix of fixes) {
        const record = await createFixRecord(
          shop, fix.resourceType, fix.resourceId, fix.resourceTitle,
          fix.fixType, fix.originalValue, fix.fixedValue,
        );
        await applyFixMock();
        await markFixApplied(record.id);
        appliedIds.push(record.id);
      }

      return json({ intent: "apply_batch", success: true, count: appliedIds.length });
    }

    case "revert": {
      const fixId = formData.get("fixId") as string;
      await revertFix(fixId);
      return json({ intent: "revert", success: true, fixId });
    }

    default:
      return json({ error: "Unknown intent" }, { status: 400 });
  }
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function Fixer() {
  const { fixableIssues, fixHistory, pendingCount, appliedCount, hasScanData, subscription } =
    useLoaderData<typeof loader>();
  const fetcher = useFetcher<any>();
  const navigate = useNavigate();

  const [selectedTab, setSelectedTab] = useState(0);
  const handleTabChange = useCallback(
    (index: number) => setSelectedTab(index),
    [],
  );

  // For preview modal
  const [previewIssue, setPreviewIssue] = useState<FixableIssue | null>(null);
  const [previewSuggestion, setPreviewSuggestion] = useState<FixSuggestion | null>(null);

  // Batch state
  const resourceIDResolver = (item: FixableIssue) => item.id;
  const { selectedResources, allResourcesSelected, handleSelectionChange } =
    useIndexResourceState(fixableIssues, { resourceIDResolver });

  const isLoading = fetcher.state !== "idle";

  // Handle fetcher responses
  const fetcherData = fetcher.data;

  const handleGenerateFix = (issue: FixableIssue) => {
    setPreviewIssue(issue);
    const formData = new FormData();
    formData.set("intent", "generate");
    formData.set("fixType", issue.fixType);
    formData.set("resourceTitle", issue.resourceTitle);
    formData.set("resourceType", issue.resourceType);
    formData.set("currentValue", issue.currentValue || "");
    formData.set("description", issue.description || "");
    fetcher.submit(formData, { method: "POST" });
  };

  const handleApplyFix = (issue: FixableIssue, fixedValue: string) => {
    const formData = new FormData();
    formData.set("intent", "apply");
    formData.set("resourceType", issue.resourceType);
    formData.set("resourceId", issue.resourceId);
    formData.set("resourceTitle", issue.resourceTitle);
    formData.set("fixType", issue.fixType);
    formData.set("originalValue", issue.currentValue || "");
    formData.set("fixedValue", fixedValue);
    fetcher.submit(formData, { method: "POST" });
    setPreviewIssue(null);
    setPreviewSuggestion(null);
  };

  const handleBatchGenerate = () => {
    const selectedIssues = fixableIssues.filter((i) =>
      selectedResources.includes(i.id),
    );
    const formData = new FormData();
    formData.set("intent", "generate_batch");
    formData.set("issues", JSON.stringify(selectedIssues.map((i) => ({
      fixType: i.fixType,
      resourceTitle: i.resourceTitle,
      resourceType: i.resourceType,
      resourceId: i.resourceId,
      currentValue: i.currentValue,
    }))));
    fetcher.submit(formData, { method: "POST" });
  };

  const handleRevert = (fixId: string) => {
    const formData = new FormData();
    formData.set("intent", "revert");
    formData.set("fixId", fixId);
    fetcher.submit(formData, { method: "POST" });
  };

  const tabs = [
    {
      id: "issues",
      content: `Issues (${fixableIssues.length})`,
      panelID: "issues-panel",
    },
    {
      id: "history",
      content: `History (${fixHistory.length})`,
      panelID: "history-panel",
    },
  ];

  return (
    <Page
      backAction={{ content: "Dashboard", url: "/app" }}
      title="SEO Fixer"
      subtitle="AI-powered SEO fix suggestions — review, apply, or revert"
    >
      <TitleBar title="SEO Fixer" />
      <BlockStack gap="500">
        {/* Status Banner */}
        {fetcherData?.intent === "apply" && fetcherData?.success && (
          <Banner tone="success" onDismiss={() => {}}>
            <p>Fix applied successfully!</p>
          </Banner>
        )}
        {fetcherData?.intent === "apply_batch" && fetcherData?.success && (
          <Banner tone="success" onDismiss={() => {}}>
            <p>{fetcherData.count} fixes applied successfully!</p>
          </Banner>
        )}
        {fetcherData?.intent === "revert" && fetcherData?.success && (
          <Banner tone="info" onDismiss={() => {}}>
            <p>Fix reverted successfully.</p>
          </Banner>
        )}
        {fetcherData?.error && (
          <Banner tone="critical" onDismiss={() => {}}>
            <p>{fetcherData.error}</p>
            {fetcherData.creditsRemaining === 0 && (
              <Button size="slim" url="/app/settings">
                Upgrade Plan
              </Button>
            )}
          </Banner>
        )}
        {fetcherData?.intent === "generate_batch" && fetcherData?.errors?.length > 0 && (
          <Banner tone="warning" onDismiss={() => {}}>
            {fetcherData.errors.map((err: string, i: number) => (
              <p key={i}>{err}</p>
            ))}
          </Banner>
        )}

        {/* Summary Cards */}
        <Layout>
          <Layout.Section variant="oneThird">
            <Card>
              <BlockStack gap="200">
                <InlineStack align="space-between">
                  <Text as="h3" variant="headingMd">Fixable Issues</Text>
                  <Badge tone={fixableIssues.length > 0 ? "attention" : "success"}>
                    {fixableIssues.length}
                  </Badge>
                </InlineStack>
                <Text as="p" variant="bodySm" tone="subdued">
                  Issues AI can help fix
                </Text>
              </BlockStack>
            </Card>
          </Layout.Section>
          <Layout.Section variant="oneThird">
            <Card>
              <BlockStack gap="200">
                <InlineStack align="space-between">
                  <Text as="h3" variant="headingMd">Applied</Text>
                  <Badge tone="success">{appliedCount}</Badge>
                </InlineStack>
                <Text as="p" variant="bodySm" tone="subdued">
                  Fixes written to your store
                </Text>
              </BlockStack>
            </Card>
          </Layout.Section>
          <Layout.Section variant="oneThird">
            <Card>
              <BlockStack gap="200">
                <InlineStack align="space-between">
                  <Text as="h3" variant="headingMd">AI Credits</Text>
                  <Badge tone={!subscription.canUseAI ? "critical" : subscription.usagePercent > 80 ? "warning" : "success"}>
                    {subscription.isUnlimited
                      ? `${subscription.aiCreditsUsed} used`
                      : `${subscription.aiCreditsUsed} / ${subscription.aiCreditsLimit}`}
                  </Badge>
                </InlineStack>
                <Text as="p" variant="bodySm" tone="subdued">
                  {subscription.plan.charAt(0).toUpperCase() + subscription.plan.slice(1)} plan
                  {subscription.isUnlimited ? " — unlimited" : ` — ${subscription.aiCreditsRemaining} remaining`}
                </Text>
                {!subscription.canUseAI && (
                  <Button size="slim" variant="primary" url="/app/settings">
                    Upgrade Plan
                  </Button>
                )}
              </BlockStack>
            </Card>
          </Layout.Section>
        </Layout>

        {/* Tab Content */}
        <Layout>
          <Layout.Section>
            <Card padding="0">
              <Tabs tabs={tabs} selected={selectedTab} onSelect={handleTabChange}>
                <Box padding="400">
                  {selectedTab === 0 ? (
                    /* Issues Tab */
                    fixableIssues.length > 0 ? (
                      <BlockStack gap="400">
                        {/* Batch Actions */}
                        {selectedResources.length > 0 && (
                          <InlineStack gap="200">
                            <Button
                              loading={isLoading && fetcherData?.intent === "generate_batch"}
                              onClick={handleBatchGenerate}
                            >
                              Generate Fixes ({selectedResources.length})
                            </Button>
                          </InlineStack>
                        )}

                        {/* Batch preview results */}
                        {fetcherData?.intent === "generate_batch" && fetcherData?.suggestions && (
                          <Banner tone="info">
                            <BlockStack gap="200">
                              <Text as="p" variant="bodyMd" fontWeight="semibold">
                                {fetcherData.suggestions.length} fix suggestions generated
                              </Text>
                              {fetcherData.suggestions.map((s: any, idx: number) => (
                                <Box key={idx} padding="200" background="bg-surface" borderRadius="100">
                                  <BlockStack gap="100">
                                    <InlineStack align="space-between">
                                      <Text as="span" variant="bodySm" fontWeight="semibold">
                                        {s.resourceTitle}
                                      </Text>
                                      <Badge>{s.fixType.replace("_", " ")}</Badge>
                                    </InlineStack>
                                    <Text as="p" variant="bodySm" tone="subdued">
                                      Original: {s.originalValue || "(empty)"}
                                    </Text>
                                    <Text as="p" variant="bodySm" tone="success">
                                      Suggested: {s.suggestedValue}
                                    </Text>
                                  </BlockStack>
                                </Box>
                              ))}
                              <Button
                                variant="primary"
                                loading={isLoading}
                                onClick={() => {
                                  const formData = new FormData();
                                  formData.set("intent", "apply_batch");
                                  formData.set("fixes", JSON.stringify(
                                    fetcherData.suggestions.map((s: any) => ({
                                      resourceType: s.resourceType,
                                      resourceId: s.resourceId,
                                      resourceTitle: s.resourceTitle,
                                      fixType: s.fixType,
                                      originalValue: s.originalValue,
                                      fixedValue: s.suggestedValue,
                                    })),
                                  ));
                                  fetcher.submit(formData, { method: "POST" });
                                }}
                              >
                                Apply All {fetcherData.suggestions.length} Fixes
                              </Button>
                            </BlockStack>
                          </Banner>
                        )}

                        {/* Issues Table */}
                        <IndexTable
                          resourceName={{ singular: "issue", plural: "issues" }}
                          itemCount={fixableIssues.length}
                          selectedItemsCount={
                            allResourcesSelected ? "All" : selectedResources.length
                          }
                          onSelectionChange={handleSelectionChange}
                          headings={[
                            { title: "Resource" },
                            { title: "Issue Type" },
                            { title: "Current Value" },
                            { title: "Severity" },
                            { title: "Action" },
                          ]}
                        >
                          {fixableIssues.map((issue, index) => (
                            <IndexTable.Row
                              id={issue.id}
                              key={issue.id}
                              position={index}
                              selected={selectedResources.includes(issue.id)}
                            >
                              <IndexTable.Cell>
                                <BlockStack gap="050">
                                  <Text as="span" variant="bodyMd" fontWeight="semibold">
                                    {issue.resourceTitle}
                                  </Text>
                                  <Text as="span" variant="bodySm" tone="subdued">
                                    {issue.resourceType}
                                  </Text>
                                </BlockStack>
                              </IndexTable.Cell>
                              <IndexTable.Cell>
                                <Badge>{formatFixType(issue.fixType)}</Badge>
                              </IndexTable.Cell>
                              <IndexTable.Cell>
                                <Tooltip content={issue.currentValue || "(empty)"}>
                                  <Text as="span" variant="bodySm" tone="subdued">
                                    {truncate(issue.currentValue || "(empty)", 40)}
                                  </Text>
                                </Tooltip>
                              </IndexTable.Cell>
                              <IndexTable.Cell>
                                <Badge tone={getSeverityTone(issue.severity)}>
                                  {issue.severity}
                                </Badge>
                              </IndexTable.Cell>
                              <IndexTable.Cell>
                                <Button
                                  size="slim"
                                  onClick={() => handleGenerateFix(issue)}
                                  loading={isLoading && previewIssue?.id === issue.id}
                                >
                                  AI Fix
                                </Button>
                              </IndexTable.Cell>
                            </IndexTable.Row>
                          ))}
                        </IndexTable>
                      </BlockStack>
                    ) : (
                      <Box padding="800">
                        <BlockStack align="center" inlineAlign="center" gap="200">
                          <Text as="p" variant="headingMd" tone="subdued">
                            {hasScanData
                              ? "No fixable issues found!"
                              : "No scan data yet"}
                          </Text>
                          <Text as="p" variant="bodySm" tone="subdued">
                            {hasScanData
                              ? "Your store's SEO looks great."
                              : "Run a scan first to detect issues."}
                          </Text>
                          {!hasScanData && (
                            <Button onClick={() => navigate("/app/scanner")}>
                              Go to Scanner
                            </Button>
                          )}
                        </BlockStack>
                      </Box>
                    )
                  ) : (
                    /* History Tab */
                    fixHistory.length > 0 ? (
                      <BlockStack gap="200">
                        {fixHistory.map((record: FixRecord) => (
                          <Box
                            key={record.id}
                            padding="300"
                            background="bg-surface-secondary"
                            borderRadius="200"
                          >
                            <InlineStack align="space-between" blockAlign="start">
                              <BlockStack gap="100">
                                <InlineStack gap="200" blockAlign="center">
                                  <Text as="span" variant="bodyMd" fontWeight="semibold">
                                    {record.resourceTitle}
                                  </Text>
                                  <Badge>{formatFixType(record.fixType as any)}</Badge>
                                  <Badge tone={getStatusTone(record.status)}>
                                    {record.status}
                                  </Badge>
                                </InlineStack>
                                <Text as="p" variant="bodySm" tone="subdued">
                                  Original: {truncate(record.originalValue || "(empty)", 60)}
                                </Text>
                                <Text as="p" variant="bodySm" tone="success">
                                  Fixed: {truncate(record.fixedValue, 60)}
                                </Text>
                                <Text as="p" variant="bodySm" tone="subdued">
                                  {new Date(record.createdAt).toLocaleString()}
                                </Text>
                              </BlockStack>
                              {record.status === "applied" && (
                                <Button
                                  size="slim"
                                  tone="critical"
                                  onClick={() => handleRevert(record.id)}
                                  loading={isLoading}
                                >
                                  Revert
                                </Button>
                              )}
                            </InlineStack>
                          </Box>
                        ))}
                      </BlockStack>
                    ) : (
                      <Box padding="800">
                        <BlockStack align="center" inlineAlign="center">
                          <Text as="p" variant="bodyMd" tone="subdued">
                            No fix history yet. Apply fixes to see them here.
                          </Text>
                        </BlockStack>
                      </Box>
                    )
                  )}
                </Box>
              </Tabs>
            </Card>
          </Layout.Section>
        </Layout>

        {/* Single Fix Preview */}
        {previewIssue && fetcherData?.intent === "generate" && fetcherData?.suggestion && (
          <Layout>
            <Layout.Section>
              <Card>
                <BlockStack gap="400">
                  <InlineStack align="space-between">
                    <Text as="h2" variant="headingMd">
                      Fix Preview — {previewIssue.resourceTitle}
                    </Text>
                    <Badge>{formatFixType(previewIssue.fixType)}</Badge>
                  </InlineStack>
                  <Divider />
                  <BlockStack gap="200">
                    <Text as="h3" variant="headingSm" tone="subdued">
                      Original
                    </Text>
                    <Box padding="300" background="bg-surface-critical" borderRadius="200">
                      <Text as="p" variant="bodyMd">
                        {fetcherData.suggestion.originalValue || "(empty)"}
                      </Text>
                    </Box>
                  </BlockStack>
                  <BlockStack gap="200">
                    <InlineStack gap="200" blockAlign="center">
                      <Text as="h3" variant="headingSm" tone="success">
                        AI Suggestion
                      </Text>
                      {fetcherData.suggestion.usedMock && (
                        <Badge tone="info">Mock mode</Badge>
                      )}
                    </InlineStack>
                    <Box padding="300" background="bg-surface-success" borderRadius="200">
                      <Text as="p" variant="bodyMd">
                        {fetcherData.suggestion.suggestedValue}
                      </Text>
                    </Box>
                  </BlockStack>
                  <Divider />
                  <InlineStack gap="200" align="end">
                    <Button
                      onClick={() => {
                        setPreviewIssue(null);
                        setPreviewSuggestion(null);
                      }}
                    >
                      Dismiss
                    </Button>
                    <Button
                      variant="primary"
                      loading={isLoading}
                      onClick={() =>
                        handleApplyFix(previewIssue, fetcherData.suggestion.suggestedValue)
                      }
                    >
                      Apply Fix
                    </Button>
                  </InlineStack>
                </BlockStack>
              </Card>
            </Layout.Section>
          </Layout>
        )}
      </BlockStack>
    </Page>
  );
}

// ---------------------------------------------------------------------------
// Types & Helpers
// ---------------------------------------------------------------------------

interface FixableIssue {
  id: string; // unique key for IndexTable
  resourceType: "product" | "collection" | "page";
  resourceId: string;
  resourceTitle: string;
  fixType: "meta_title" | "meta_description" | "alt_text" | "product_description";
  currentValue: string | null;
  severity: string;
  message: string;
  description?: string;
}

function extractFixableIssues(results: SeoCheckResult[]): FixableIssue[] {
  const issues: FixableIssue[] = [];
  const ruleToFixType: Record<string, FixableIssue["fixType"]> = {
    "meta-title-length": "meta_title",
    "meta-description-length": "meta_description",
    "image-alt-text": "alt_text",
  };

  for (const result of results) {
    for (const issue of result.issues) {
      const fixType = ruleToFixType[issue.ruleId];
      if (!fixType) continue; // Skip non-fixable issues (H1, URL slug, duplicates)

      let currentValue: string | null = null;
      if (fixType === "meta_title") {
        currentValue = result.metadata.metaTitle;
      } else if (fixType === "meta_description") {
        currentValue = result.metadata.metaDescription;
      }

      issues.push({
        id: `${result.resourceId}:${issue.ruleId}`,
        resourceType: result.resourceType as FixableIssue["resourceType"],
        resourceId: result.resourceId,
        resourceTitle: result.resourceTitle,
        fixType,
        currentValue,
        severity: issue.severity,
        message: issue.message,
      });
    }
  }

  return issues;
}

function formatFixType(type: string): string {
  const names: Record<string, string> = {
    meta_title: "Meta Title",
    meta_description: "Meta Description",
    alt_text: "Alt Text",
    product_description: "Description",
  };
  return names[type] || type;
}

function getSeverityTone(severity: string): "critical" | "warning" | "info" {
  if (severity === "critical") return "critical";
  if (severity === "warning") return "warning";
  return "info";
}

function getStatusTone(status: string): "success" | "warning" | "info" {
  if (status === "applied") return "success";
  if (status === "pending") return "warning";
  return "info";
}

function truncate(str: string, maxLen: number): string {
  return str.length > maxLen ? str.substring(0, maxLen - 3) + "..." : str;
}
