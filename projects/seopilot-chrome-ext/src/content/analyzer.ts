/**
 * Content Script — Injected into web pages to perform SEO analysis.
 *
 * This script is executed via chrome.scripting.executeScript from the popup.
 * It analyzes the current page's DOM and returns the results.
 */

import { analyzePage, type AnalysisResult } from "./seo-checks";

// Run analysis and return result
(function (): AnalysisResult {
  return analyzePage(document);
})();
