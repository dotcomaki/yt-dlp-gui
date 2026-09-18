// Shared settings-object helpers. Loaded as a plain <script> by index.html
// (so these are just ordinary globals in the webview) and also required
// directly by tests/test_deepmerge.js via the module.exports guard below —
// same functions, no duplication between the app and its tests.

function getPath(obj, path) {
  return path.split('.').reduce((o, k) => (o == null ? o : o[k]), obj);
}

function setPath(obj, path, value) {
  const keys = path.split('.');
  const last = keys.pop();
  const target = keys.reduce((o, k) => o[k], obj);
  target[last] = value;
}

// Merges saved values onto the current defaults, keyed off the
// defaults' own shape — missing/extra/mistyped keys in a settings
// file from an older version of the app are silently ignored rather
// than crashing or clobbering a field with the wrong type.
function deepMerge(target, source) {
  if (typeof source !== 'object' || source === null) return target;
  for (const key of Object.keys(target)) {
    if (!(key in source)) continue;
    const sVal = source[key];
    const tVal = target[key];
    if (tVal && typeof tVal === 'object' && !Array.isArray(tVal) && sVal && typeof sVal === 'object') {
      deepMerge(tVal, sVal);
    } else if (typeof sVal === typeof tVal) {
      target[key] = sVal;
    }
  }
  return target;
}

// A canonical string for "these settings + this folder" so the app can tell
// whether the live state still matches the profile that was applied.
// Normalizes through the defaults' shape (key order and unknown keys don't
// matter) and blanks the password, which profiles never store anyway.
function settingsFingerprint(defaults, settings, destFolder) {
  const merged = deepMerge(JSON.parse(JSON.stringify(defaults)), settings || {});
  if (merged.auth && typeof merged.auth === 'object') merged.auth.password = '';
  return JSON.stringify({ settings: merged, destFolder: destFolder || '' });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { getPath, setPath, deepMerge, settingsFingerprint };
}
