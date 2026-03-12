/**
 * Shopify GraphQL mutations for writing SEO fixes back to the store.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type AdminGraphQLClient = {
  graphql: (query: string, options?: { variables?: Record<string, unknown> }) => Promise<Response>;
};

export interface ApplyFixResult {
  success: boolean;
  error?: string;
}

// ---------------------------------------------------------------------------
// GraphQL Mutations
// ---------------------------------------------------------------------------

const UPDATE_PRODUCT_SEO = `#graphql
  mutation UpdateProductSEO($input: ProductInput!) {
    productUpdate(input: $input) {
      product {
        id
        title
        seo {
          title
          description
        }
      }
      userErrors {
        field
        message
      }
    }
  }
`;

const UPDATE_PRODUCT_IMAGE_ALT = `#graphql
  mutation UpdateProductImageAlt($productId: ID!, $mediaId: ID!, $altText: String!) {
    productUpdateMedia(
      productId: $productId
      media: [{ id: $mediaId, alt: $altText }]
    ) {
      media {
        ... on MediaImage {
          id
          alt
        }
      }
      mediaUserErrors {
        field
        message
      }
    }
  }
`;

const UPDATE_COLLECTION_SEO = `#graphql
  mutation UpdateCollectionSEO($input: CollectionInput!) {
    collectionUpdate(input: $input) {
      collection {
        id
        title
        seo {
          title
          description
        }
      }
      userErrors {
        field
        message
      }
    }
  }
`;

const UPDATE_PAGE_SEO = `#graphql
  mutation UpdatePageSEO($id: ID!, $page: PageUpdateInput!) {
    pageUpdate(id: $id, page: $page) {
      page {
        id
        title
        seo {
          title
          description
        }
      }
      userErrors {
        field
        message
      }
    }
  }
`;

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Apply a product SEO fix via GraphQL mutation.
 */
export async function applyProductSeoFix(
  admin: AdminGraphQLClient,
  productId: string,
  field: "seoTitle" | "seoDescription" | "description",
  value: string,
): Promise<ApplyFixResult> {
  try {
    const input: Record<string, unknown> = { id: productId };

    if (field === "seoTitle") {
      input.seo = { title: value };
    } else if (field === "seoDescription") {
      input.seo = { description: value };
    } else if (field === "description") {
      input.descriptionHtml = value;
    }

    const response = await admin.graphql(UPDATE_PRODUCT_SEO, {
      variables: { input },
    });

    const json = await response.json();
    const errors = json.data?.productUpdate?.userErrors;

    if (errors && errors.length > 0) {
      return { success: false, error: errors.map((e: any) => e.message).join("; ") };
    }

    return { success: true };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

/**
 * Apply a collection SEO fix via GraphQL mutation.
 */
export async function applyCollectionSeoFix(
  admin: AdminGraphQLClient,
  collectionId: string,
  field: "seoTitle" | "seoDescription",
  value: string,
): Promise<ApplyFixResult> {
  try {
    const input: Record<string, unknown> = { id: collectionId };

    if (field === "seoTitle") {
      input.seo = { title: value };
    } else {
      input.seo = { description: value };
    }

    const response = await admin.graphql(UPDATE_COLLECTION_SEO, {
      variables: { input },
    });

    const json = await response.json();
    const errors = json.data?.collectionUpdate?.userErrors;

    if (errors && errors.length > 0) {
      return { success: false, error: errors.map((e: any) => e.message).join("; ") };
    }

    return { success: true };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

/**
 * Apply a page SEO fix via GraphQL mutation.
 */
export async function applyPageSeoFix(
  admin: AdminGraphQLClient,
  pageId: string,
  field: "seoTitle" | "seoDescription" | "body",
  value: string,
): Promise<ApplyFixResult> {
  try {
    const page: Record<string, unknown> = {};

    if (field === "seoTitle") {
      page.seo = { title: value };
    } else if (field === "seoDescription") {
      page.seo = { description: value };
    } else if (field === "body") {
      page.body = value;
    }

    const response = await admin.graphql(UPDATE_PAGE_SEO, {
      variables: { id: pageId, page },
    });

    const json = await response.json();
    const errors = json.data?.pageUpdate?.userErrors;

    if (errors && errors.length > 0) {
      return { success: false, error: errors.map((e: any) => e.message).join("; ") };
    }

    return { success: true };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

/**
 * Apply a product image alt text fix via GraphQL mutation.
 */
export async function applyImageAltFix(
  admin: AdminGraphQLClient,
  productId: string,
  mediaId: string,
  altText: string,
): Promise<ApplyFixResult> {
  try {
    const response = await admin.graphql(UPDATE_PRODUCT_IMAGE_ALT, {
      variables: { productId, mediaId, altText },
    });

    const json = await response.json();
    const errors = json.data?.productUpdateMedia?.mediaUserErrors;

    if (errors && errors.length > 0) {
      return { success: false, error: errors.map((e: any) => e.message).join("; ") };
    }

    return { success: true };
  } catch (error: any) {
    return { success: false, error: error.message };
  }
}

/**
 * Apply a fix using mock mode (just returns success without calling Shopify).
 * Used when Shopify Partner account is not available.
 */
export async function applyFixMock(): Promise<ApplyFixResult> {
  return { success: true };
}
