/**
 * Background Service Worker — Handles badge updates and message routing.
 */

chrome.runtime.onMessage.addListener(
  (
    message: { type: string; score?: number; color?: string },
    _sender,
    sendResponse,
  ) => {
    if (message.type === "UPDATE_BADGE") {
      const score = message.score ?? 0;
      const color = message.color ?? "red";

      const colorMap: Record<string, string> = {
        red: "#EF4444",
        yellow: "#F59E0B",
        green: "#22C55E",
      };

      // Get the active tab to set the badge
      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        const tabId = tabs[0]?.id;
        if (tabId === undefined) return;

        chrome.action.setBadgeText({ text: String(score), tabId });
        chrome.action.setBadgeBackgroundColor({
          color: colorMap[color] || "#EF4444",
          tabId,
        });
        chrome.action.setBadgeTextColor({ color: "#FFFFFF", tabId });
      });

      sendResponse({ success: true });
    }

    return true; // Keep message channel open for async response
  },
);

// Clear badge when tab navigates
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading") {
    chrome.action.setBadgeText({ text: "", tabId });
  }
});
