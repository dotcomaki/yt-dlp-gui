// The toolbar popup: confirm the URL, pick a saved profile, and either
// start the download in the background or open the app with it filled in.
const HOST_NAME = "com.dotcomaki.ytdlpgui";
const urlInput = document.getElementById("url");
const profileSelect = document.getElementById("profile");
const statusLine = document.getElementById("status");
const nowBtn = document.getElementById("now");
const openBtn = document.getElementById("open");

function say(text, isError) {
  statusLine.textContent = text;
  statusLine.classList.toggle("err", !!isError);
}

function send(message) {
  return new Promise((resolve) => {
    chrome.runtime.sendNativeMessage(HOST_NAME, message, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message });
        return;
      }
      resolve(response || { ok: false, error: "no response from the yt-dlp GUI host" });
    });
  });
}

// Profiles live in the app's config file, which the native host reads —
// the app itself doesn't have to be running.
async function loadProfiles() {
  const result = await send({ action: "profiles" });
  if (!result.ok || !result.profiles || !result.profiles.length) return;
  result.profiles.forEach((name) => profileSelect.add(new Option(name, name)));
  const { lastProfile } = await chrome.storage.local.get("lastProfile");
  if (lastProfile && result.profiles.includes(lastProfile)) profileSelect.value = lastProfile;
}

async function submit(enqueue) {
  const url = urlInput.value.trim();
  if (!url) { say("Nothing to download.", true); return; }
  nowBtn.disabled = openBtn.disabled = true;
  say(enqueue ? "Sending…" : "Opening…");
  const result = await send({ url, profile: profileSelect.value, enqueue });
  if (!result.ok) {
    say(result.error || "The yt-dlp GUI host didn't answer.", true);
    nowBtn.disabled = openBtn.disabled = false;
    return;
  }
  chrome.storage.local.set({ lastProfile: profileSelect.value });
  say(result.delivered === "launched" ? "Starting the app…" : (enqueue ? "Queued." : "Sent."));
  setTimeout(() => window.close(), 550);
}

nowBtn.addEventListener("click", () => submit(true));
openBtn.addEventListener("click", () => submit(false));
urlInput.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(true); });

chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  const url = tabs[0] && tabs[0].url;
  if (url && /^https?:\/\//i.test(url)) urlInput.value = url;
  else say("This page isn't something yt-dlp can fetch — paste a URL instead.");
  loadProfiles();
});
