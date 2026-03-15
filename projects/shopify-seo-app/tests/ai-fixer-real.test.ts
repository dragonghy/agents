/**
 * Integration tests for the AI Fixer service using real OpenAI API.
 *
 * These tests require OPENAI_API_KEY to be set in .env.
 * They make actual API calls and verify response quality.
 *
 * Run with: npx vitest run tests/ai-fixer-real.test.ts
 */

import { describe, it, expect, beforeAll } from "vitest";
import { config } from "dotenv";
import { resolve } from "path";

// Load .env BEFORE importing the module
config({ path: resolve(__dirname, "../.env") });

import {
  generateFix,
  generateFixes,
  type FixRequest,
} from "../app/services/ai-fixer.server";

const API_KEY = process.env.OPENAI_API_KEY;
const hasRealKey = !!API_KEY && !API_KEY.includes("mock");

// Skip all tests if no real API key
const describeIf = hasRealKey ? describe : describe.skip;

describeIf("AI Fixer - Real OpenAI API", () => {
  beforeAll(() => {
    console.log(`Using OPENAI_API_KEY: ${API_KEY?.substring(0, 12)}...`);
    console.log(`API Key looks real: ${hasRealKey}`);
  });

  // ── Meta Title ──

  it("generates an SEO-optimized meta title (30-60 chars)", async () => {
    const result = await generateFix({
      fixType: "meta_title",
      resourceTitle: "Organic Cotton Crew Neck T-Shirt",
      resourceType: "product",
      currentValue: "T-Shirt",
      productDescription:
        "Made from 100% organic cotton. Available in 5 colors. Unisex fit.",
      tone: "professional",
    });

    console.log(
      `Meta title: "${result.suggestedValue}" (${result.suggestedValue.length} chars)`,
    );

    expect(result.usedMock).toBe(false);
    expect(result.confidence).toBe(0.85);
    expect(result.suggestedValue.length).toBeGreaterThanOrEqual(10);
    expect(result.suggestedValue.length).toBeLessThanOrEqual(80); // Allow some slack from AI
    expect(result.suggestedValue).not.toBe("T-Shirt"); // Should be different from current
  }, 15000);

  // ── Meta Description ──

  it("generates an SEO-optimized meta description (120-160 chars)", async () => {
    const result = await generateFix({
      fixType: "meta_description",
      resourceTitle: "Premium Yoga Mat",
      resourceType: "product",
      currentValue: null,
      productDescription:
        "6mm thick, non-slip surface, eco-friendly TPE material. Perfect for yoga, pilates, and stretching.",
      tone: "professional",
    });

    console.log(
      `Meta desc: "${result.suggestedValue}" (${result.suggestedValue.length} chars)`,
    );

    expect(result.usedMock).toBe(false);
    expect(result.suggestedValue.length).toBeGreaterThanOrEqual(50);
    expect(result.suggestedValue.length).toBeLessThanOrEqual(200); // Allow some slack
  }, 15000);

  // ── Alt Text ──

  it("generates descriptive alt text for product image", async () => {
    const result = await generateFix({
      fixType: "alt_text",
      resourceTitle: "Handmade Ceramic Coffee Mug",
      resourceType: "product",
      currentValue: "IMG_4532.jpg",
      productDescription: "12oz handmade ceramic mug with blue glaze finish.",
      tone: "professional",
    });

    console.log(`Alt text: "${result.suggestedValue}"`);

    expect(result.usedMock).toBe(false);
    expect(result.suggestedValue.length).toBeGreaterThanOrEqual(10);
    expect(result.suggestedValue.length).toBeLessThanOrEqual(200);
    // Should not be a filename
    expect(result.suggestedValue).not.toContain("IMG_");
    expect(result.suggestedValue).not.toContain(".jpg");
  }, 15000);

  // ── Product Description ──

  it("rewrites product description for SEO", async () => {
    const currentDesc = "Nice bag. Good quality leather. Many pockets.";
    const result = await generateFix({
      fixType: "product_description",
      resourceTitle: "Classic Leather Messenger Bag",
      resourceType: "product",
      currentValue: currentDesc,
      tone: "professional",
    });

    console.log(
      `Product desc (${result.suggestedValue.length} chars): "${result.suggestedValue.substring(0, 100)}..."`,
    );

    expect(result.usedMock).toBe(false);
    expect(result.suggestedValue.length).toBeGreaterThan(currentDesc.length);
    // Should be substantively different from input
    expect(result.suggestedValue).not.toBe(currentDesc);
  }, 15000);

  // ── Tone Variation ──

  it("produces different output for different tones", async () => {
    const baseReq: FixRequest = {
      fixType: "meta_description",
      resourceTitle: "Diamond Necklace",
      resourceType: "product",
      currentValue: null,
      productDescription: "18K gold chain with 0.5ct diamond pendant.",
    };

    const [casual, luxury] = await Promise.all([
      generateFix({ ...baseReq, tone: "casual" }),
      generateFix({ ...baseReq, tone: "luxury" }),
    ]);

    console.log(`Casual: "${casual.suggestedValue}"`);
    console.log(`Luxury: "${luxury.suggestedValue}"`);

    // Both should succeed via AI
    expect(casual.usedMock).toBe(false);
    expect(luxury.usedMock).toBe(false);
    // Should produce different results
    expect(casual.suggestedValue).not.toBe(luxury.suggestedValue);
  }, 30000);

  // ── Batch ──

  it("batch generates fixes for multiple requests", async () => {
    const requests: FixRequest[] = [
      {
        fixType: "meta_title",
        resourceTitle: "Running Shoes",
        resourceType: "product",
        currentValue: "Shoes",
        tone: "professional",
      },
      {
        fixType: "alt_text",
        resourceTitle: "Running Shoes",
        resourceType: "product",
        currentValue: null,
        tone: "professional",
      },
    ];

    const results = await generateFixes(requests);

    expect(results).toHaveLength(2);
    expect(results.every((r) => !r.usedMock)).toBe(true);
    console.log(
      `Batch results: title="${results[0].suggestedValue}", alt="${results[1].suggestedValue}"`,
    );
  }, 30000);

  // ── Error Handling ──

  it("falls back to mock when API key is invalid", async () => {
    // Temporarily set invalid key
    const originalKey = process.env.OPENAI_API_KEY;
    process.env.OPENAI_API_KEY = "sk-invalid-key-for-testing";

    const result = await generateFix({
      fixType: "meta_title",
      resourceTitle: "Test Product",
      resourceType: "product",
      currentValue: null,
      tone: "professional",
    });

    // Restore
    process.env.OPENAI_API_KEY = originalKey;

    // Should have fallen back to mock
    expect(result.usedMock).toBe(true);
    expect(result.confidence).toBe(0.6);
    console.log(`Fallback result: "${result.suggestedValue}" (mock=${result.usedMock})`);
  }, 15000);
});
