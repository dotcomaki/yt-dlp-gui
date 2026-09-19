const YOUTUBE_PATTERN = /^https:\/\/(www\.)?youtube\.com\//;
const HOST_NAME = "com.dotcomaki.ytdlpgui";

function updateActionForTab(tabId, url) {
  const isYouTube = !!url && YOUTUBE_PATTERN.test(url);
  const suffix = isYouTube ? "" : "-disabled";
  chrome.action.setIcon({
    tabId,
    path: { 16: `icon16${suffix}.png`, 48: `icon48${suffix}.png`, 128: `icon128${suffix}.png` },
  });
  if (isYouTube) {
    chrome.action.enable(tabId);
  } else {
    chrome.action.disable(tabId);
  }
}

function syncAllTabs() {
  chrome.tabs.query({}, (tabs) => {
    tabs.forEach((tab) => updateActionForTab(tab.id, tab.url));
  });
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.url || changeInfo.status === "complete") {
    updateActionForTab(tabId, tab.url);
  }
});

chrome.tabs.onActivated.addListener(({ tabId }) => {
  chrome.tabs.get(tabId, (tab) => {
    if (chrome.runtime.lastError || !tab) return;
    updateActionForTab(tabId, tab.url);
  });
});

// onInstalled only fires once per install/update; onStartup covers the
// case where Chrome was relaunched and the service worker starts fresh.
chrome.runtime.onInstalled.addListener(syncAllTabs);
chrome.runtime.onStartup.addListener(syncAllTabs);

// A click has no visible result of its own (the app may be behind the
// browser), so flash a badge: ✓ when the host took the URL, ! when it
// didn't — otherwise a broken host registration looks like nothing.
function flashBadge(tabId, ok) {
  chrome.action.setBadgeBackgroundColor({ tabId, color: ok ? "#32d74b" : "#ff453a" });
  chrome.action.setBadgeText({ tabId, text: ok ? "✓" : "!" });
  setTimeout(() => chrome.action.setBadgeText({ tabId, text: "" }), 2000);
}

chrome.action.onClicked.addListener((tab) => {
  if (!tab.url || !YOUTUBE_PATTERN.test(tab.url)) return;
  chrome.runtime.sendNativeMessage(HOST_NAME, { url: tab.url }, (response) => {
    if (chrome.runtime.lastError) {
      console.error("yt-dlp native host error:", chrome.runtime.lastError.message);
      flashBadge(tab.id, false);
      return;
    }
    flashBadge(tab.id, !!(response && response.ok));
  });
});
