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
  Divider,
  ProgressBar,
  Select,
  Checkbox,
} from "@shopify/polaris";
import { TitleBar } from "@shopify/app-bridge-react";
import { useState, useCallback } from "react";
import { useLoaderData, useFetcher } from "@remix-run/react";
import { authenticate } from "../shopify.server";
import {
  getSubscriptionInfo,
  changePlan,
  getAllPlans,
  type PlanConfig,
  type PlanId,
} from "../services/billing.server";
import db from "../db.server";

// ---------------------------------------------------------------------------
// Loader
// ---------------------------------------------------------------------------
export const loader = async ({ request }: LoaderFunctionArgs) => {
  const { session } = await authenticate.admin(request);
  const shop = session.shop;

  const [subscriptionInfo, userSettings] = await Promise.all([
    getSubscriptionInfo(shop),
    db.userSettings.findUnique({ where: { shop } }),
  ]);

  const plans = getAllPlans();

  return json({
    subscription: {
      plan: subscriptionInfo.plan,
      planName: subscriptionInfo.planConfig.name,
      aiCreditsUsed: subscriptionInfo.aiCreditsUsed,
      aiCreditsLimit: subscriptionInfo.aiCreditsLimit,
      aiCreditsRemaining: subscriptionInfo.isUnlimited ? -1 : (subscriptionInfo.aiCreditsLimit - subscriptionInfo.aiCreditsUsed),
      isUnlimited: subscriptionInfo.isUnlimited,
      canUseAI: subscriptionInfo.canUseAI,
      usagePercent: subscriptionInfo.usagePercent,
      billingCycleStart: subscriptionInfo.billingCycleStart.toISOString(),
      status: subscriptionInfo.status,
    },
    plans: plans.map((p) => ({
      ...p,
      aiCreditsLimit: p.aiCreditsLimit === -1 ? "Unlimited" : p.aiCreditsLimit,
    })),
    settings: {
      aiTone: userSettings?.aiTone || "professional",
      scanFrequency: userSettings?.scanFrequency || "weekly",
      autoScanEnabled: userSettings?.autoScanEnabled || false,
      notificationEmail: userSettings?.notificationEmail || "",
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

  switch (intent) {
    case "change_plan": {
      const newPlan = formData.get("plan") as PlanId;
      const result = await changePlan(shop, newPlan, { mock: true });

      if (!result.success) {
        return json({
          intent: "change_plan",
          success: false,
          error: result.error,
        });
      }

      if (result.confirmationUrl) {
        return json({
          intent: "change_plan",
          success: true,
          confirmationUrl: result.confirmationUrl,
        });
      }

      return json({ intent: "change_plan", success: true });
    }

    case "update_settings": {
      const aiTone = formData.get("aiTone") as string;
      const scanFrequency = formData.get("scanFrequency") as string;
      const autoScanEnabled = formData.get("autoScanEnabled") === "true";

      await db.userSettings.upsert({
        where: { shop },
        create: {
          shop,
          aiTone,
          scanFrequency,
          autoScanEnabled,
        },
        update: {
          aiTone,
          scanFrequency,
          autoScanEnabled,
        },
      });

      return json({ intent: "update_settings", success: true });
    }

    default:
      return json({ error: "Unknown intent" }, { status: 400 });
  }
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function Settings() {
  const { subscription, plans, settings } = useLoaderData<typeof loader>();
  const fetcher = useFetcher<any>();

  const [aiTone, setAiTone] = useState(settings.aiTone);
  const [scanFrequency, setScanFrequency] = useState(settings.scanFrequency);
  const [autoScanEnabled, setAutoScanEnabled] = useState(settings.autoScanEnabled);

  const isLoading = fetcher.state !== "idle";
  const fetcherData = fetcher.data;

  const handlePlanChange = useCallback(
    (planId: string) => {
      if (planId === subscription.plan) return;
      const formData = new FormData();
      formData.set("intent", "change_plan");
      formData.set("plan", planId);
      fetcher.submit(formData, { method: "POST" });
    },
    [subscription.plan, fetcher],
  );

  const handleSaveSettings = useCallback(() => {
    const formData = new FormData();
    formData.set("intent", "update_settings");
    formData.set("aiTone", aiTone);
    formData.set("scanFrequency", scanFrequency);
    formData.set("autoScanEnabled", autoScanEnabled.toString());
    fetcher.submit(formData, { method: "POST" });
  }, [aiTone, scanFrequency, autoScanEnabled, fetcher]);

  return (
    <Page
      backAction={{ content: "Dashboard", url: "/app" }}
      title="Settings & Pricing"
      subtitle="Manage your subscription and preferences"
    >
      <TitleBar title="Settings" />
      <BlockStack gap="500">
        {/* Status Banners */}
        {fetcherData?.intent === "change_plan" && fetcherData?.success && (
          <Banner tone="success" onDismiss={() => {}}>
            <p>Plan updated successfully!</p>
          </Banner>
        )}
        {fetcherData?.intent === "change_plan" && fetcherData?.error && (
          <Banner tone="critical" onDismiss={() => {}}>
            <p>{fetcherData.error}</p>
          </Banner>
        )}
        {fetcherData?.intent === "update_settings" && fetcherData?.success && (
          <Banner tone="success" onDismiss={() => {}}>
            <p>Settings saved successfully!</p>
          </Banner>
        )}

        {/* Current Plan & Usage */}
        <Layout>
          <Layout.Section>
            <Card>
              <BlockStack gap="400">
                <InlineStack align="space-between" blockAlign="center">
                  <Text as="h2" variant="headingLg">
                    Current Plan
                  </Text>
                  <Badge tone="success">
                    {subscription.planName}
                  </Badge>
                </InlineStack>
                <Divider />
                <BlockStack gap="300">
                  <Text as="h3" variant="headingMd">
                    AI Credits Usage
                  </Text>
                  <InlineStack align="space-between">
                    <Text as="p" variant="bodyMd">
                      {subscription.isUnlimited
                        ? `${subscription.aiCreditsUsed} credits used (unlimited)`
                        : `${subscription.aiCreditsUsed} / ${subscription.aiCreditsLimit} credits used`}
                    </Text>
                    {!subscription.isUnlimited && (
                      <Text as="p" variant="bodySm" tone={subscription.canUseAI ? "subdued" : "critical"}>
                        {subscription.aiCreditsRemaining} remaining
                      </Text>
                    )}
                  </InlineStack>
                  {!subscription.isUnlimited && (
                    <ProgressBar
                      progress={subscription.usagePercent}
                      tone={subscription.usagePercent >= 90 ? "critical" : subscription.usagePercent >= 70 ? "highlight" : "success"}
                      size="small"
                    />
                  )}
                  <Text as="p" variant="bodySm" tone="subdued">
                    Billing cycle started: {new Date(subscription.billingCycleStart).toLocaleDateString()}
                  </Text>
                </BlockStack>
              </BlockStack>
            </Card>
          </Layout.Section>
        </Layout>

        {/* Plan Comparison */}
        <Layout>
          {plans.map((plan: any) => (
            <Layout.Section key={plan.id} variant="oneThird">
              <Card
                background={plan.id === subscription.plan ? "bg-surface-success" : undefined}
              >
                <BlockStack gap="400">
                  <InlineStack align="space-between" blockAlign="center">
                    <Text as="h2" variant="headingLg">
                      {plan.name}
                    </Text>
                    {plan.recommended && (
                      <Badge tone="info">Recommended</Badge>
                    )}
                  </InlineStack>
                  <InlineStack gap="100" blockAlign="baseline">
                    <Text as="p" variant="heading2xl" fontWeight="bold">
                      ${plan.price}
                    </Text>
                    {plan.price > 0 && (
                      <Text as="p" variant="bodyMd" tone="subdued">
                        / month
                      </Text>
                    )}
                  </InlineStack>
                  <Divider />
                  <BlockStack gap="200">
                    <InlineStack gap="200">
                      <Text as="span" variant="bodyMd" fontWeight="semibold">
                        AI Credits:
                      </Text>
                      <Text as="span" variant="bodyMd">
                        {plan.aiCreditsLimit === "Unlimited" ? "Unlimited" : `${plan.aiCreditsLimit}/month`}
                      </Text>
                    </InlineStack>
                    {plan.features.map((feature: string, idx: number) => (
                      <InlineStack key={idx} gap="200" blockAlign="center">
                        <Text as="span" variant="bodySm" tone="success">
                          &#10003;
                        </Text>
                        <Text as="span" variant="bodySm">
                          {feature}
                        </Text>
                      </InlineStack>
                    ))}
                  </BlockStack>
                  <Box paddingBlockStart="200">
                    {plan.id === subscription.plan ? (
                      <Button disabled fullWidth>
                        Current Plan
                      </Button>
                    ) : (
                      <Button
                        variant={plan.id === "pro" ? "primary" : undefined}
                        fullWidth
                        loading={isLoading}
                        onClick={() => handlePlanChange(plan.id)}
                      >
                        {plan.price > (plans.find((p: any) => p.id === subscription.plan)?.price || 0)
                          ? `Upgrade to ${plan.name}`
                          : `Switch to ${plan.name}`}
                      </Button>
                    )}
                  </Box>
                </BlockStack>
              </Card>
            </Layout.Section>
          ))}
        </Layout>

        {/* Settings */}
        <Layout>
          <Layout.Section>
            <Card>
              <BlockStack gap="400">
                <Text as="h2" variant="headingLg">
                  Preferences
                </Text>
                <Divider />
                <Select
                  label="AI Tone"
                  helpText="Controls the writing style for AI-generated content"
                  options={[
                    { label: "Professional — clear & informative", value: "professional" },
                    { label: "Casual — friendly & conversational", value: "casual" },
                    { label: "Luxury — elegant & sophisticated", value: "luxury" },
                  ]}
                  value={aiTone}
                  onChange={(v) => setAiTone(v)}
                />
                <Select
                  label="Auto-Scan Frequency"
                  helpText="How often to automatically scan your store for SEO issues"
                  options={[
                    { label: "Daily", value: "daily" },
                    { label: "Weekly", value: "weekly" },
                    { label: "Monthly", value: "monthly" },
                  ]}
                  value={scanFrequency}
                  onChange={(v) => setScanFrequency(v)}
                />
                <Checkbox
                  label="Enable automatic scanning"
                  helpText="Automatically scan your store according to the schedule above"
                  checked={autoScanEnabled}
                  onChange={(v) => setAutoScanEnabled(v)}
                />
                <InlineStack align="end">
                  <Button variant="primary" onClick={handleSaveSettings} loading={isLoading}>
                    Save Settings
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
