import type { LoaderFunctionArgs } from "@remix-run/node";
import {
  Page,
  Layout,
  Text,
  Card,
  BlockStack,
  Collapsible,
  InlineStack,
  Button,
  Divider,
  Link,
  List,
  Box,
} from "@shopify/polaris";
import { TitleBar } from "@shopify/app-bridge-react";
import { useState, useCallback } from "react";
import { authenticate } from "../shopify.server";

// ---------------------------------------------------------------------------
// Loader
// ---------------------------------------------------------------------------
export const loader = async ({ request }: LoaderFunctionArgs) => {
  await authenticate.admin(request);
  return null;
};

// ---------------------------------------------------------------------------
// FAQ Data
// ---------------------------------------------------------------------------
interface FaqItem {
  question: string;
  answer: string;
}

const faqSections: Array<{ title: string; items: FaqItem[] }> = [
  {
    title: "Getting Started",
    items: [
      {
        question: "How do I run my first SEO scan?",
        answer:
          "Navigate to the Scanner page from the sidebar. Select which resource types you want to scan (Products, Collections, Pages), then click \"Start Scan\". The scan will analyze all your content and provide an SEO health score along with detailed issue reports.",
      },
      {
        question: "What does the SEO score mean?",
        answer:
          "The SEO score (0-100) represents overall SEO health of your store. It's calculated based on weighted checks including meta title length (30-60 chars ideal), meta description length (120-160 chars ideal), image alt text presence, H1 tag structure, URL slug optimization, and duplicate content detection. A score of 80+ is excellent, 60-79 is good, and below 60 needs attention.",
      },
      {
        question: "Do I need a Shopify Partner account?",
        answer:
          "No. SEOPilot works with any Shopify store. The app uses your store's Admin API access granted during installation. In development/demo mode, the app uses mock data to demonstrate all features.",
      },
    ],
  },
  {
    title: "AI Fixer",
    items: [
      {
        question: "How does the AI Fix feature work?",
        answer:
          "The AI Fixer uses OpenAI (GPT-4o-mini) to generate optimized SEO content. When you click \"AI Fix\" on an issue, it analyzes your product/page context and generates an improved version. You always get to preview and approve the suggestion before it's applied to your store.",
      },
      {
        question: "What are AI credits?",
        answer:
          "Each AI fix generation uses one credit. The Free plan includes 10 credits per month, Pro includes 100, and Business has unlimited credits. Credits reset at the start of each billing cycle. You can check your remaining credits on the Fixer page or Settings page.",
      },
      {
        question: "Can I revert an applied fix?",
        answer:
          "Yes! Every fix is tracked in the History tab on the Fixer page. Click \"Revert\" on any applied fix to restore the original value. This makes it safe to experiment with AI suggestions.",
      },
      {
        question: "What AI tones are available?",
        answer:
          "SEOPilot offers three AI writing tones: Professional (clear and informative), Casual (friendly and conversational), and Luxury (elegant and sophisticated). You can set your preferred tone in Settings. Business plan users get access to custom tone configuration.",
      },
      {
        question: "What if the AI suggestion isn't good enough?",
        answer:
          "You can click \"AI Fix\" again to generate a new suggestion. Each generation uses one credit. You can also edit the suggestion manually before applying. The AI continuously improves, and providing more detailed product descriptions helps generate better results.",
      },
    ],
  },
  {
    title: "Plans & Billing",
    items: [
      {
        question: "What's included in the Free plan?",
        answer:
          "The Free plan includes basic SEO scanning for all resource types, 10 AI fix credits per month, SEO score dashboard, and fix history with rollback. It's great for small stores getting started with SEO.",
      },
      {
        question: "How do I upgrade my plan?",
        answer:
          "Go to Settings & Pricing in the sidebar. You'll see a comparison of all plans. Click \"Upgrade\" on your desired plan. The charge will be processed through Shopify's billing system and appear on your Shopify invoice.",
      },
      {
        question: "Can I downgrade my plan?",
        answer:
          "Yes, you can switch to a lower plan at any time from the Settings page. Your current billing cycle will remain active until its end. Note that downgrading may reduce your AI credit limit.",
      },
      {
        question: "When do AI credits reset?",
        answer:
          "AI credits reset at the start of each monthly billing cycle. Unused credits do not roll over to the next month.",
      },
    ],
  },
  {
    title: "Troubleshooting",
    items: [
      {
        question: "Why does my scan show 0 results?",
        answer:
          "If your store has no products, collections, or pages, the scan will show 0 results. Make sure you have content published in your store. In demo mode, mock data is used to demonstrate the scanning feature.",
      },
      {
        question: "Why can't I use the AI Fixer?",
        answer:
          "Check your AI credit balance on the Fixer page. If you've used all your credits for the month, you'll need to wait for the next billing cycle or upgrade your plan for more credits.",
      },
      {
        question: "The app seems slow. What can I do?",
        answer:
          "Large stores with hundreds of products may take longer to scan. Try scanning one resource type at a time. If the issue persists, try clearing your browser cache and reloading the app.",
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function Help() {
  const [openItems, setOpenItems] = useState<Record<string, boolean>>({});

  const toggleItem = useCallback((id: string) => {
    setOpenItems((prev) => ({ ...prev, [id]: !prev[id] }));
  }, []);

  return (
    <Page
      backAction={{ content: "Dashboard", url: "/app" }}
      title="Help & FAQ"
      subtitle="Frequently asked questions and support resources"
    >
      <TitleBar title="Help" />
      <BlockStack gap="500">
        {/* Quick Links */}
        <Layout>
          <Layout.Section>
            <Card>
              <BlockStack gap="300">
                <Text as="h2" variant="headingLg">
                  Quick Links
                </Text>
                <InlineStack gap="300" wrap>
                  <Button url="/app/scanner">Run a Scan</Button>
                  <Button url="/app/fixer">Fix Issues</Button>
                  <Button url="/app/settings">Manage Plan</Button>
                  <Button url="/app/privacy">Privacy Policy</Button>
                </InlineStack>
              </BlockStack>
            </Card>
          </Layout.Section>
        </Layout>

        {/* FAQ Sections */}
        {faqSections.map((section, sectionIdx) => (
          <Layout key={sectionIdx}>
            <Layout.Section>
              <Card>
                <BlockStack gap="400">
                  <Text as="h2" variant="headingLg">
                    {section.title}
                  </Text>
                  <Divider />
                  <BlockStack gap="200">
                    {section.items.map((item, itemIdx) => {
                      const itemId = `${sectionIdx}-${itemIdx}`;
                      const isOpen = openItems[itemId] || false;
                      return (
                        <Box key={itemId}>
                          <Box
                            padding="300"
                            background={isOpen ? "bg-surface-secondary" : undefined}
                            borderRadius="200"
                          >
                            <BlockStack gap="200">
                              <InlineStack
                                align="space-between"
                                blockAlign="center"
                              >
                                <Box>
                                  <Button
                                    variant="plain"
                                    textAlign="left"
                                    onClick={() => toggleItem(itemId)}
                                  >
                                    <Text
                                      as="span"
                                      variant="bodyMd"
                                      fontWeight="semibold"
                                    >
                                      {isOpen ? "▼" : "▶"} {item.question}
                                    </Text>
                                  </Button>
                                </Box>
                              </InlineStack>
                              <Collapsible
                                open={isOpen}
                                id={`faq-${itemId}`}
                                transition={{
                                  duration: "200ms",
                                  timingFunction: "ease-in-out",
                                }}
                              >
                                <Box paddingInlineStart="400" paddingBlockStart="200">
                                  <Text as="p" variant="bodyMd">
                                    {item.answer}
                                  </Text>
                                </Box>
                              </Collapsible>
                            </BlockStack>
                          </Box>
                          {itemIdx < section.items.length - 1 && <Divider />}
                        </Box>
                      );
                    })}
                  </BlockStack>
                </BlockStack>
              </Card>
            </Layout.Section>
          </Layout>
        ))}

        {/* Contact Support */}
        <Layout>
          <Layout.Section>
            <Card>
              <BlockStack gap="300">
                <Text as="h2" variant="headingLg">
                  Need More Help?
                </Text>
                <Text as="p" variant="bodyMd">
                  Can't find what you're looking for? Our support team is here to help.
                </Text>
                <InlineStack gap="300">
                  <Button variant="primary" url="mailto:support@seopilot.app">
                    Contact Support
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
