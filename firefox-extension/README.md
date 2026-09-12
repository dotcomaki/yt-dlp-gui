# Firefox extension

Same behavior as the Chrome/Arc extension — clicking the toolbar icon on a YouTube page launches the yt-dlp GUI with that video's URL pre-filled. `background.js` and the icons are symlinked from `../extension/` (identical logic; Firefox implements the same `chrome.*` API namespace), only `manifest.json` differs, since Firefox's extension ID and background-script declaration work differently from Chrome's.

> This uses the **Nightly/unsigned route** — matching how the Chrome extension is set up (load it locally, no store submission). Regular release-channel Firefox requires every extension to be signed by Mozilla to install persistently; Nightly and Developer Edition let you turn that requirement off.

## Setup

1. **Use Firefox Nightly or Developer Edition** — regular release Firefox won't allow disabling signature enforcement.

2. **Disable signature enforcement**: go to `about:config`, search for `xpinstall.signatures.required`, and set it to `false`.

3. **Register the native messaging host**:
   ```bash
   ./install.sh
   ```
   Installs the manifest into Firefox's own directory (`~/Library/Application Support/Mozilla/NativeMessagingHosts/` on macOS, `~/.mozilla/native-messaging-hosts/` on Linux — different from Chrome's directories, and using `allowed_extensions` with a gecko ID instead of Chrome's `allowed_origins`). Untested on Linux — written to Mozilla's documented path.

4. **Build the extension package**:
   ```bash
   ./build.sh
   ```
   Produces `ytdlp-gui.xpi` in this folder (a plain zip with the symlinked files resolved into real copies — Firefox's installer doesn't follow symlinks). Needs the `zip` command — present by default on macOS, but not guaranteed on a minimal Linux install (`sudo apt install zip` or your distro's equivalent if `build.sh` reports it missing).

5. **Install it**: `about:addons` → gear icon (⚙) → **Install Add-on From File...** → select `ytdlp-gui.xpi`. This persists across restarts, unlike the temporary-load method below.

6. Fully quit and relaunch Firefox, then pin the extension's icon to the toolbar if it isn't already visible.

## Faster iteration while developing

Instead of rebuilding the `.xpi` on every change, use `about:debugging` → **This Firefox** → **Load Temporary Add-on** → select `manifest.json` directly. This skips signing entirely and loads instantly, but unloads whenever Firefox restarts — good for testing changes, not for a setup you want to stick around.

## Re-running after moving the project

If you move or re-clone this project, re-run `./install.sh` (the native host manifest has an absolute path baked in — Firefox's native messaging spec requires that, same as Chrome's) and `./build.sh` if the extension itself changed.
