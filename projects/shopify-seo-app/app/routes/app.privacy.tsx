import type { LoaderFunctionArgs } from "@remix-run/node";
import {
  Page,
  Layout,
  Text,
  Card,
  BlockStack,
  Box,
  Divider,
  List,
} from "@shopify/polaris";
import { TitleBar } from "@shopify/app-bridge-react";
import { authenticate } from "../shopify.server";

// ---------------------------------------------------------------------------
// Loader
// ---------------------------------------------------------------------------
export const loader = async ({ request }: LoaderFunctionArgs) => {
  await authenticate.admin(request);
  return null;
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function Privacy() {
  return (
    <Page
      backAction={{ content: "Dashboard", url: "/app" }}
      title="Privacy Policy"
    >
      <TitleBar title="Privacy Policy" />
      <BlockStack gap="500">
        <Layout>
          <Layout.Section>
            <Card>
              <BlockStack gap="400">
                <Text as="h2" variant="headingLg">
                  SEOPilot Privacy Policy
                </Text>
                <Text as="p" variant="bodySm" tone="subdued">
                  Last updated: March 2026
                </Text>
                <Divider />

                <BlockStack gap="300">
                  <Text as="h3" variant="headingMd">
                    1. Information We Collect
                  </Text>
                  <Text as="p" variant="bodyMd">
                    SEOPilot accesses only the data necessary to provide SEO analysis and optimization for your Shopify store:
                  </Text>
                  <List>
                    <List.Item>
                      <strong>Product data:</strong> Titles, descriptions, images, and SEO metadata (meta titles, meta descriptions)
                    </List.Item>
                    <List.Item>
                      <strong>Collection data:</strong> Titles, descriptions, and SEO metadata
                    </List.Item>
                    <List.Item>
                      <strong>Page data:</strong> Titles, body content, and SEO metadata
                    </List.Item>
                    <List.Item>
                      <strong>Store information:</strong> Shop domain (used for authentication and data association)
                    </List.Item>
                  </List>
                </BlockStack>

                <BlockStack gap="300">
                  <Text as="h3" variant="headingMd">
                    2. How We Use Your Data
                  </Text>
                  <List>
                    <List.Item>
                      <strong>SEO Analysis:</strong> We scan your product, collection, and page data to identify SEO issues and calculate SEO health scores.
                    </List.Item>
                    <List.Item>
                      <strong>AI-Generated Suggestions:</strong> When you use the AI Fixer feature, relevant content (titles, descriptions) is sent to OpenAI to generate optimized alternatives. This data is not stored by OpenAI for training purposes.
                    </List.Item>
                    <List.Item>
                      <strong>Fix History:</strong> We store records of fixes you apply so you can review and revert them if needed.
                    </List.Item>
                    <List.Item>
                      <strong>Subscription Management:</strong> We track your plan type and AI credit usage to enforce plan limits.
                    </List.Item>
                  </List>
                </BlockStack>

                <BlockStack gap="300">
                  <Text as="h3" variant="headingMd">
                    3. Data Storage
                  </Text>
                  <Text as="p" variant="bodyMd">
                    All data is stored securely in our PostgreSQL database hosted on secure cloud infrastructure. We use encryption in transit (TLS/SSL) for all data transfers. Scan results and fix history are associated with your shop domain and are not shared with other merchants.
                  </Text>
                </BlockStack>

                <BlockStack gap="300">
                  <Text as="h3" variant="headingMd">
                    4. Third-Party Services
                  </Text>
                  <List>
                    <List.Item>
                      <strong>OpenAI:</strong> Used for AI-powered SEO content generation. Only relevant product/page content is shared when you explicitly request an AI fix. Data is processed per OpenAI&apos;s API data usage policy and is not used for model training.
                    </List.Item>
                    <List.Item>
                      <strong>Shopify:</strong> We access your store data through the Shopify Admin API with the permissions you grant during installation.
                    </List.Item>
                  </List>
                </BlockStack>

                <BlockStack gap="300">
                  <Text as="h3" variant="headingMd">
                    5. Data Retention
                  </Text>
                  <Text as="p" variant="bodyMd">
                    Scan results are retained until a new scan is performed (only the latest scan is kept). Fix history is retained for your reference. Upon uninstalling the app, all associated data (scan results, fix history, settings, subscription records) is deleted within 48 hours.
                  </Text>
                </BlockStack>

                <BlockStack gap="300">
                  <Text as="h3" variant="headingMd">
                    6. Your Rights
                  </Text>
                  <List>
                    <List.Item>
                      <strong>Access:</strong> You can view all data we store via the app dashboard.
                    </List.Item>
                    <List.Item>
                      <strong>Deletion:</strong> Uninstalling the app will remove all your data. You can also contact us to request deletion.
                    </List.Item>
                    <List.Item>
                      <strong>Portability:</strong> Contact us to request an export of your data.
                    </List.Item>
                  </List>
                </BlockStack>

                <BlockStack gap="300">
                  <Text as="h3" variant="headingMd">
                    7. Contact
                  </Text>
                  <Text as="p" variant="bodyMd">
                    For privacy-related questions, please contact us at privacy@seopilot.app.
                  </Text>
                </BlockStack>
              </BlockStack>
            </Card>
          </Layout.Section>
        </Layout>
      </BlockStack>
    </Page>
  );
}
