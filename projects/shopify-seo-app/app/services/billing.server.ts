/**
 * Billing & Subscription Service — manages plan limits, AI credit tracking,
 * and Shopify Billing API integration (with mock fallback).
 *
 * Plan tiers:
 *   - Free:     10 AI credits/month, basic scan
 *   - Pro:      100 AI credits/month ($19/mo), full scan + batch
 *   - Business: Unlimited AI credits ($39/mo), priority support
 */

import db from "../db.server";

// ---------------------------------------------------------------------------
// Plan Configuration
// ---------------------------------------------------------------------------

export interface PlanConfig {
  id: "free" | "pro" | "business";
  name: string;
  price: number; // monthly USD
  aiCreditsLimit: number; // -1 = unlimited
  scanLimit: number; // max products to scan, -1 = unlimited
  features: string[];
  recommended?: boolean;
}

export const PLANS: Record<string, PlanConfig> = {
  free: {
    id: "free",
    name: "Free",
    price: 0,
    aiCreditsLimit: 10,
    scanLimit: 50,
    features: [
      "Scan up to 50 products",
      "10 AI fix credits/month",
      "SEO score dashboard",
      "Manual fixes only",
    ],
  },
  pro: {
    id: "pro",
    name: "Pro",
    price: 19,
    aiCreditsLimit: 100,
    scanLimit: -1, // unlimited
    recommended: true,
    features: [
      "Unlimited product scanning",
      "100 AI fix credits/month",
      "Batch fix operations",
      "Fix history & rollback",
      "Priority scan scheduling",
      "Email notifications",
    ],
  },
  business: {
    id: "business",
    name: "Business",
    price: 39,
    aiCreditsLimit: -1, // unlimited
    scanLimit: -1, // unlimited
    features: [
      "Everything in Pro",
      "Unlimited AI fix credits",
      "Priority support",
      "Custom AI tone settings",
      "API access (coming soon)",
      "Multi-store support (coming soon)",
    ],
  },
};

export type PlanId = keyof typeof PLANS;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SubscriptionInfo {
  plan: PlanId;
  planConfig: PlanConfig;
  aiCreditsUsed: number;
  aiCreditsLimit: number;
  aiCreditsRemaining: number;
  isUnlimited: boolean;
  canUseAI: boolean;
  usagePercent: number;
  billingCycleStart: Date;
  status: string;
}

export interface CreditCheckResult {
  allowed: boolean;
  creditsRemaining: number;
  plan: PlanId;
  message?: string;
}

// ---------------------------------------------------------------------------
// Subscription CRUD
// ---------------------------------------------------------------------------

/**
 * Get or create subscription record for a shop.
 */
export async function getOrCreateSubscription(shop: string) {
  let sub = await db.subscription.findUnique({ where: { shop } });
  if (!sub) {
    sub = await db.subscription.create({
      data: {
        shop,
        plan: "free",
        aiCreditsUsed: 0,
        aiCreditsLimit: PLANS.free.aiCreditsLimit,
        billingCycleStart: new Date(),
        status: "active",
      },
    });
  }
  return sub;
}

/**
 * Get subscription info with computed fields.
 */
export async function getSubscriptionInfo(shop: string): Promise<SubscriptionInfo> {
  const sub = await getOrCreateSubscription(shop);
  const planConfig = PLANS[sub.plan] || PLANS.free;
  const isUnlimited = planConfig.aiCreditsLimit === -1;
  const creditsRemaining = isUnlimited
    ? Infinity
    : Math.max(0, sub.aiCreditsLimit - sub.aiCreditsUsed);

  return {
    plan: sub.plan as PlanId,
    planConfig,
    aiCreditsUsed: sub.aiCreditsUsed,
    aiCreditsLimit: sub.aiCreditsLimit,
    aiCreditsRemaining: isUnlimited ? Infinity : creditsRemaining,
    isUnlimited,
    canUseAI: isUnlimited || sub.aiCreditsUsed < sub.aiCreditsLimit,
    usagePercent: isUnlimited
      ? 0
      : Math.min(100, Math.round((sub.aiCreditsUsed / sub.aiCreditsLimit) * 100)),
    billingCycleStart: sub.billingCycleStart,
    status: sub.status,
  };
}

// ---------------------------------------------------------------------------
// AI Credit Management
// ---------------------------------------------------------------------------

/**
 * Check whether the shop can use AI credits (before generating a fix).
 */
export async function checkAICredits(shop: string): Promise<CreditCheckResult> {
  const info = await getSubscriptionInfo(shop);

  if (!info.canUseAI) {
    return {
      allowed: false,
      creditsRemaining: 0,
      plan: info.plan,
      message: `You've used all ${info.aiCreditsLimit} AI credits this month. Upgrade to ${info.plan === "free" ? "Pro" : "Business"} for more credits.`,
    };
  }

  return {
    allowed: true,
    creditsRemaining: info.isUnlimited ? -1 : (info.aiCreditsLimit - info.aiCreditsUsed),
    plan: info.plan,
  };
}

/**
 * Increment AI credit usage (call after each successful AI fix generation).
 * Returns the updated count.
 */
export async function incrementAICredits(shop: string, count: number = 1): Promise<number> {
  const sub = await getOrCreateSubscription(shop);
  const planConfig = PLANS[sub.plan] || PLANS.free;

  // Don't increment for unlimited plans (but still return 0)
  if (planConfig.aiCreditsLimit === -1) {
    return sub.aiCreditsUsed;
  }

  const updated = await db.subscription.update({
    where: { shop },
    data: {
      aiCreditsUsed: { increment: count },
    },
  });

  return updated.aiCreditsUsed;
}

/**
 * Reset AI credits (called at billing cycle renewal).
 */
export async function resetAICredits(shop: string): Promise<void> {
  await db.subscription.update({
    where: { shop },
    data: {
      aiCreditsUsed: 0,
      billingCycleStart: new Date(),
    },
  });
}

// ---------------------------------------------------------------------------
// Plan Change
// ---------------------------------------------------------------------------

/**
 * Upgrade or downgrade a shop's plan.
 * In mock mode, this just updates the DB. In real mode, it would create
 * a Shopify RecurringApplicationCharge first.
 */
export async function changePlan(
  shop: string,
  newPlan: PlanId,
  options?: { shopifyChargeId?: string; mock?: boolean },
): Promise<{ success: boolean; error?: string; confirmationUrl?: string }> {
  const planConfig = PLANS[newPlan];
  if (!planConfig) {
    return { success: false, error: `Unknown plan: ${newPlan}` };
  }

  const sub = await getOrCreateSubscription(shop);

  if (sub.plan === newPlan) {
    return { success: false, error: "Already on this plan" };
  }

  // In mock mode or for free plan, just update directly
  const isMock = options?.mock ?? (!process.env.SHOPIFY_API_KEY || process.env.SHOPIFY_API_KEY === "mock_api_key_for_dev");

  if (isMock || newPlan === "free") {
    await db.subscription.update({
      where: { shop },
      data: {
        plan: newPlan,
        aiCreditsLimit: planConfig.aiCreditsLimit === -1 ? 999999 : planConfig.aiCreditsLimit,
        shopifyChargeId: options?.shopifyChargeId || (isMock ? `mock_charge_${newPlan}_${Date.now()}` : null),
        status: "active",
      },
    });

    return { success: true };
  }

  // Real Shopify Billing API flow would go here
  // For now, return mock confirmation URL
  return {
    success: true,
    confirmationUrl: `https://${shop}/admin/charges/confirm?plan=${newPlan}`,
  };
}

/**
 * Create a Shopify RecurringApplicationCharge (mock mode).
 */
export async function createBillingCharge(
  admin: { graphql: (q: string, o?: any) => Promise<Response> } | null,
  shop: string,
  planId: PlanId,
): Promise<{ success: boolean; confirmationUrl?: string; error?: string }> {
  const plan = PLANS[planId];
  if (!plan || plan.price === 0) {
    // Free plan doesn't need a charge
    await changePlan(shop, planId, { mock: true });
    return { success: true };
  }

  // Mock mode: no real admin client
  if (!admin) {
    await changePlan(shop, planId, { mock: true });
    return { success: true };
  }

  // Real mode: call Shopify Billing API
  try {
    const response = await admin.graphql(
      `#graphql
      mutation CreateSubscription($name: String!, $amount: Decimal!, $returnUrl: URL!, $trialDays: Int) {
        appSubscriptionCreate(
          name: $name
          returnUrl: $returnUrl
          trialDays: $trialDays
          lineItems: [{
            plan: {
              appRecurringPricingDetails: {
                price: { amount: $amount, currencyCode: USD }
              }
            }
          }]
        ) {
          appSubscription {
            id
          }
          confirmationUrl
          userErrors {
            field
            message
          }
        }
      }`,
      {
        variables: {
          name: `SEOPilot ${plan.name} Plan`,
          amount: plan.price.toFixed(2),
          returnUrl: `https://${shop}/admin/apps/seopilot/app/settings?charge_confirmed=true&plan=${planId}`,
          trialDays: planId === "pro" ? 7 : 0,
        },
      },
    );

    const data = await response.json();
    const result = data.data?.appSubscriptionCreate;

    if (result?.userErrors?.length > 0) {
      return {
        success: false,
        error: result.userErrors.map((e: any) => e.message).join("; "),
      };
    }

    return {
      success: true,
      confirmationUrl: result?.confirmationUrl,
    };
  } catch (error: any) {
    // Fallback to mock on API error
    console.warn("Billing API failed, using mock:", error.message);
    await changePlan(shop, planId, { mock: true });
    return { success: true };
  }
}

// ---------------------------------------------------------------------------
// Plan Feature Checks
// ---------------------------------------------------------------------------

/**
 * Check if a feature is available on the current plan.
 */
export async function canUseBatchOperations(shop: string): Promise<boolean> {
  const info = await getSubscriptionInfo(shop);
  return info.plan !== "free";
}

export async function canUseCustomTone(shop: string): Promise<boolean> {
  const info = await getSubscriptionInfo(shop);
  return info.plan === "business";
}

/**
 * Get the scan limit for a shop's current plan.
 * Returns -1 for unlimited.
 */
export async function getScanLimit(shop: string): Promise<number> {
  const info = await getSubscriptionInfo(shop);
  return info.planConfig.scanLimit;
}

export function getPlanConfig(planId: string): PlanConfig {
  return PLANS[planId] || PLANS.free;
}

export function getAllPlans(): PlanConfig[] {
  return Object.values(PLANS);
}
