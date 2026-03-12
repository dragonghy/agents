/**
 * Unit tests for the Billing & Subscription service.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";

// We test the plan configuration and logic directly
// (DB-dependent functions are tested via integration tests)

// ---------------------------------------------------------------------------
// Plan Configuration Tests
// ---------------------------------------------------------------------------

describe("Billing - Plan Configuration", () => {
  it("has three plans: free, pro, business", async () => {
    // Dynamic import to avoid module resolution issues with Prisma
    const { PLANS } = await import("../app/services/billing.server");
    expect(Object.keys(PLANS)).toEqual(["free", "pro", "business"]);
  });

  it("free plan has correct limits", async () => {
    const { PLANS } = await import("../app/services/billing.server");
    expect(PLANS.free.price).toBe(0);
    expect(PLANS.free.aiCreditsLimit).toBe(10);
    expect(PLANS.free.features.length).toBeGreaterThan(0);
  });

  it("pro plan costs $19 with 100 credits", async () => {
    const { PLANS } = await import("../app/services/billing.server");
    expect(PLANS.pro.price).toBe(19);
    expect(PLANS.pro.aiCreditsLimit).toBe(100);
    expect(PLANS.pro.recommended).toBe(true);
  });

  it("business plan costs $39 with unlimited credits", async () => {
    const { PLANS } = await import("../app/services/billing.server");
    expect(PLANS.business.price).toBe(39);
    expect(PLANS.business.aiCreditsLimit).toBe(-1); // unlimited
  });

  it("getAllPlans returns all three plans", async () => {
    const { getAllPlans } = await import("../app/services/billing.server");
    const plans = getAllPlans();
    expect(plans).toHaveLength(3);
    expect(plans.map((p) => p.id)).toEqual(["free", "pro", "business"]);
  });

  it("getPlanConfig returns correct config", async () => {
    const { getPlanConfig } = await import("../app/services/billing.server");
    const pro = getPlanConfig("pro");
    expect(pro.name).toBe("Pro");
    expect(pro.price).toBe(19);
  });

  it("getPlanConfig falls back to free for unknown plan", async () => {
    const { getPlanConfig } = await import("../app/services/billing.server");
    const unknown = getPlanConfig("nonexistent");
    expect(unknown.id).toBe("free");
    expect(unknown.price).toBe(0);
  });

  it("each plan has at least 3 features", async () => {
    const { PLANS } = await import("../app/services/billing.server");
    for (const [id, plan] of Object.entries(PLANS)) {
      expect(plan.features.length).toBeGreaterThanOrEqual(3);
    }
  });

  it("plan prices are ascending", async () => {
    const { getAllPlans } = await import("../app/services/billing.server");
    const plans = getAllPlans();
    for (let i = 1; i < plans.length; i++) {
      expect(plans[i].price).toBeGreaterThanOrEqual(plans[i - 1].price);
    }
  });

  it("plan credit limits are ascending (with -1 = unlimited as highest)", async () => {
    const { getAllPlans } = await import("../app/services/billing.server");
    const plans = getAllPlans();
    // Free=10, Pro=100, Business=-1(unlimited)
    expect(plans[0].aiCreditsLimit).toBe(10);
    expect(plans[1].aiCreditsLimit).toBe(100);
    expect(plans[2].aiCreditsLimit).toBe(-1);
  });
});
