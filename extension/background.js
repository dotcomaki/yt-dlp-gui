// yt-dlp handles ~1,800 sites plus a generic extractor for anything with
// a media file on the page, so the only tabs the button can't do anything
// with are the browser's own (chrome://, about:, file:, extension pages).
const DOWNLOADABLE = /^https?:\/\//i;
const HOST_NAME = "com.dotcomaki.ytdlpgui";
const MENU_ID = "ytdlp-download";

function updateActionForTab(tabId, url) {
  const ok = !!url && DOWNLOADABLE.test(url);
  const suffix = ok ? "" : "-disabled";
  chrome.action.setIcon({
    tabId,
    path: { 16: `icon16${suffix}.png`, 48: `icon48${suffix}.png`, 128: `icon128${suffix}.png` },
  });
  if (ok) {
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

// Right-click on a link, a <video>/<audio>, or the page itself. Menus
// outlive the service worker, so create them once at install (removeAll
// first: an update re-runs this and duplicate ids are an error).
function installMenu() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: MENU_ID,
      title: "Download with yt-dlp",
      contexts: ["link", "video", "audio", "page"],
      documentUrlPatterns: ["http://*/*", "https://*/*"],
    });
  });
}

// onInstalled only fires once per install/update; onStartup covers the
// case where the browser was relaunched and the service worker starts fresh.
chrome.runtime.onInstalled.addListener(() => { syncAllTabs(); installMenu(); });
chrome.runtime.onStartup.addListener(syncAllTabs);

// A click has no visible result of its own (the app may be behind the
// browser), so flash a badge: ✓ when the host took the URL, ! when it
// didn't — otherwise a broken host registration looks like nothing.
function flashBadge(tabId, ok) {
  chrome.action.setBadgeBackgroundColor({ tabId, color: ok ? "#32d74b" : "#ff453a" });
  chrome.action.setBadgeText({ tabId, text: ok ? "✓" : "!" });
  setTimeout(() => chrome.action.setBadgeText({ tabId, text: "" }), 2000);
}

function sendUrl(url, tabId) {
  if (!url || !DOWNLOADABLE.test(url)) return;
  chrome.runtime.sendNativeMessage(HOST_NAME, { url }, (response) => {
    if (chrome.runtime.lastError) {
      console.error("yt-dlp native host error:", chrome.runtime.lastError.message);
      if (tabId != null) flashBadge(tabId, false);
      return;
    }
    if (tabId != null) flashBadge(tabId, !!(response && response.ok));
  });
}

chrome.action.onClicked.addListener((tab) => sendUrl(tab.url, tab.id));

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== MENU_ID) return;
  // A link's target beats the media element's src beats the page: a
  // YouTube thumbnail link is what the user meant, not the page they're on.
  sendUrl(info.linkUrl || info.srcUrl || info.pageUrl, tab && tab.id);
});
