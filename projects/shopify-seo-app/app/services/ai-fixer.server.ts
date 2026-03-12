/**
 * AI Fixer Service — generates SEO fix suggestions using OpenAI or mock fallback.
 *
 * When OPENAI_API_KEY is not configured, uses rule-based mock generation
 * to produce reasonable fix suggestions.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type FixType =
  | "meta_title"
  | "meta_description"
  | "alt_text"
  | "product_description";

export type AiTone = "professional" | "casual" | "luxury";

export interface FixRequest {
  fixType: FixType;
  resourceTitle: string;
  resourceType: "product" | "collection" | "page";
  currentValue: string | null;
  productDescription?: string; // extra context for AI
  tone?: AiTone;
}

export interface FixSuggestion {
  fixType: FixType;
  originalValue: string | null;
  suggestedValue: string;
  confidence: number; // 0-1
  usedMock: boolean;
}

// ---------------------------------------------------------------------------
// OpenAI integration
// ---------------------------------------------------------------------------

const OPENAI_API_URL = "https://api.openai.com/v1/chat/completions";
const MODEL = "gpt-4o-mini";

function getApiKey(): string | null {
  return process.env.OPENAI_API_KEY || null;
}

async function callOpenAI(
  systemPrompt: string,
  userPrompt: string,
): Promise<string> {
  const apiKey = getApiKey();
  if (!apiKey) throw new Error("OPENAI_API_KEY not configured");

  const response = await fetch(OPENAI_API_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: MODEL,
      messages: [
        { role: "system", content: systemPrompt },
        { role: "user", content: userPrompt },
      ],
      temperature: 0.7,
      max_tokens: 300,
    }),
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`OpenAI API error (${response.status}): ${err}`);
  }

  const data = await response.json();
  return data.choices?.[0]?.message?.content?.trim() || "";
}

// ---------------------------------------------------------------------------
// Prompt templates
// ---------------------------------------------------------------------------

function getToneInstruction(tone: AiTone): string {
  switch (tone) {
    case "casual":
      return "Use a friendly, conversational tone.";
    case "luxury":
      return "Use an elegant, premium, sophisticated tone.";
    case "professional":
    default:
      return "Use a professional, clear, and informative tone.";
  }
}

function buildMetaTitlePrompt(req: FixRequest): { system: string; user: string } {
  return {
    system: `You are an SEO expert. Generate an optimized meta title for a Shopify ${req.resourceType}. ${getToneInstruction(req.tone || "professional")} The title MUST be between 30-60 characters. Include relevant keywords. Return ONLY the title text, nothing else.`,
    user: `Resource: "${req.resourceTitle}"\nCurrent meta title: "${req.currentValue || "(none)"}"\n${req.productDescription ? `Description: "${req.productDescription}"` : ""}\n\nGenerate an optimized meta title (30-60 characters):`,
  };
}

function buildMetaDescriptionPrompt(req: FixRequest): { system: string; user: string } {
  return {
    system: `You are an SEO expert. Generate an optimized meta description for a Shopify ${req.resourceType}. ${getToneInstruction(req.tone || "professional")} The description MUST be between 120-160 characters. Make it compelling to increase click-through rate. Return ONLY the description text, nothing else.`,
    user: `Resource: "${req.resourceTitle}"\nCurrent meta description: "${req.currentValue || "(none)"}"\n${req.productDescription ? `Product info: "${req.productDescription}"` : ""}\n\nGenerate an optimized meta description (120-160 characters):`,
  };
}

function buildAltTextPrompt(req: FixRequest): { system: string; user: string } {
  return {
    system: `You are an SEO expert. Generate descriptive alt text for a product image. ${getToneInstruction(req.tone || "professional")} The alt text should be concise (under 125 characters), descriptive, and include relevant keywords. Return ONLY the alt text, nothing else.`,
    user: `Product: "${req.resourceTitle}"\n${req.productDescription ? `Description: "${req.productDescription}"` : ""}\n\nGenerate descriptive image alt text:`,
  };
}

function buildProductDescriptionPrompt(req: FixRequest): { system: string; user: string } {
  return {
    system: `You are an SEO copywriter. Rewrite the product description to be more SEO-friendly. ${getToneInstruction(req.tone || "professional")} Include relevant keywords naturally. Keep the description engaging and informative. Maintain similar length. Return ONLY the improved description, nothing else.`,
    user: `Product: "${req.resourceTitle}"\nCurrent description: "${req.currentValue || "(none)"}"\n\nRewrite as SEO-optimized description:`,
  };
}

// ---------------------------------------------------------------------------
// Mock fallback generators
// ---------------------------------------------------------------------------

function mockMetaTitle(req: FixRequest): string {
  const title = req.resourceTitle;
  const suffixes: Record<string, string> = {
    professional: " - Shop Now",
    casual: " - Check It Out",
    luxury: " - Premium Quality",
  };
  const suffix = suffixes[req.tone || "professional"] || " - Shop Now";

  // Aim for 30-60 chars
  let result = title;
  if (result.length > 50) {
    // Truncate and add suffix
    result = result.substring(0, 50 - suffix.length) + suffix;
  } else if (result.length < 25) {
    result = result + suffix;
  }

  // Ensure within bounds
  if (result.length > 60) result = result.substring(0, 57) + "...";
  return result;
}

function mockMetaDescription(req: FixRequest): string {
  const title = req.resourceTitle;
  const desc = req.productDescription || req.currentValue || "";
  const toneText: Record<string, string> = {
    professional: `Discover ${title}. ${desc ? desc.substring(0, 80) : "High-quality product for your needs"}. Shop now with free shipping on qualifying orders.`,
    casual: `Looking for ${title}? ${desc ? desc.substring(0, 80) : "We've got exactly what you need"}. Check it out and grab yours today!`,
    luxury: `Experience the exquisite ${title}. ${desc ? desc.substring(0, 80) : "Crafted with precision and care"}. Elevate your collection today.`,
  };

  let result = toneText[req.tone || "professional"] || toneText.professional;

  // Ensure 120-160 chars
  if (result.length < 120) {
    result += " Browse our full collection for more options and exclusive deals.";
  }
  if (result.length > 160) {
    result = result.substring(0, 157) + "...";
  }
  return result;
}

function mockAltText(req: FixRequest): string {
  const title = req.resourceTitle;
  return `${title} - product image`;
}

function mockProductDescription(req: FixRequest): string {
  const current = req.currentValue || "";
  if (current.length > 20) {
    // Add SEO-friendly intro/outro
    return `Discover our ${req.resourceTitle.toLowerCase()}. ${current} Perfect for everyday use. Shop now and enjoy fast shipping.`;
  }
  return `Introducing the ${req.resourceTitle} — designed for quality and built to last. Whether you need it for work, play, or everyday life, this product delivers on every front. Order yours today and experience the difference.`;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Generate a fix suggestion for a single SEO issue.
 * Uses OpenAI if available, otherwise falls back to mock generation.
 */
export async function generateFix(req: FixRequest): Promise<FixSuggestion> {
  const apiKey = getApiKey();

  if (apiKey) {
    try {
      return await generateWithAI(req);
    } catch (error) {
      console.warn("OpenAI call failed, falling back to mock:", error);
      return generateWithMock(req);
    }
  }

  return generateWithMock(req);
}

/**
 * Generate fix suggestions for multiple issues (batch).
 */
export async function generateFixes(
  requests: FixRequest[],
): Promise<FixSuggestion[]> {
  // Process sequentially to avoid rate limits
  const results: FixSuggestion[] = [];
  for (const req of requests) {
    results.push(await generateFix(req));
  }
  return results;
}

/**
 * Generate a fix with AI credit checking and tracking.
 * Returns an error message instead of suggestion if credits exhausted.
 */
export async function generateFixWithCredits(
  shop: string,
  req: FixRequest,
): Promise<{ suggestion?: FixSuggestion; error?: string; creditsRemaining?: number }> {
  const { checkAICredits, incrementAICredits } = await import("./billing.server");

  const creditCheck = await checkAICredits(shop);
  if (!creditCheck.allowed) {
    return {
      error: creditCheck.message || "AI credits exhausted. Please upgrade your plan.",
      creditsRemaining: 0,
    };
  }

  const suggestion = await generateFix(req);

  // Increment credit usage after successful generation
  const newUsed = await incrementAICredits(shop);

  return {
    suggestion,
    creditsRemaining: creditCheck.creditsRemaining === -1
      ? -1
      : creditCheck.creditsRemaining - 1,
  };
}

/**
 * Generate fixes for multiple issues with credit tracking.
 * Stops generating if credits run out mid-batch.
 */
export async function generateFixesWithCredits(
  shop: string,
  requests: FixRequest[],
): Promise<{
  suggestions: FixSuggestion[];
  errors: string[];
  creditsRemaining: number;
  stoppedAtIndex?: number;
}> {
  const { checkAICredits, incrementAICredits, getSubscriptionInfo } = await import("./billing.server");

  const suggestions: FixSuggestion[] = [];
  const errors: string[] = [];

  for (let i = 0; i < requests.length; i++) {
    const creditCheck = await checkAICredits(shop);
    if (!creditCheck.allowed) {
      errors.push(
        `Credit limit reached after ${i} fixes. ${creditCheck.message}`,
      );
      const info = await getSubscriptionInfo(shop);
      return {
        suggestions,
        errors,
        creditsRemaining: 0,
        stoppedAtIndex: i,
      };
    }

    const suggestion = await generateFix(requests[i]);
    await incrementAICredits(shop);
    suggestions.push(suggestion);
  }

  const info = await getSubscriptionInfo(shop);
  return {
    suggestions,
    errors,
    creditsRemaining: info.isUnlimited ? -1 : (info.aiCreditsLimit - info.aiCreditsUsed),
  };
}

// ---------------------------------------------------------------------------
// Internal
// ---------------------------------------------------------------------------

async function generateWithAI(req: FixRequest): Promise<FixSuggestion> {
  let prompts: { system: string; user: string };

  switch (req.fixType) {
    case "meta_title":
      prompts = buildMetaTitlePrompt(req);
      break;
    case "meta_description":
      prompts = buildMetaDescriptionPrompt(req);
      break;
    case "alt_text":
      prompts = buildAltTextPrompt(req);
      break;
    case "product_description":
      prompts = buildProductDescriptionPrompt(req);
      break;
  }

  const result = await callOpenAI(prompts.system, prompts.user);

  return {
    fixType: req.fixType,
    originalValue: req.currentValue,
    suggestedValue: result,
    confidence: 0.85,
    usedMock: false,
  };
}

function generateWithMock(req: FixRequest): FixSuggestion {
  let suggestedValue: string;

  switch (req.fixType) {
    case "meta_title":
      suggestedValue = mockMetaTitle(req);
      break;
    case "meta_description":
      suggestedValue = mockMetaDescription(req);
      break;
    case "alt_text":
      suggestedValue = mockAltText(req);
      break;
    case "product_description":
      suggestedValue = mockProductDescription(req);
      break;
  }

  return {
    fixType: req.fixType,
    originalValue: req.currentValue,
    suggestedValue,
    confidence: 0.6,
    usedMock: true,
  };
}
