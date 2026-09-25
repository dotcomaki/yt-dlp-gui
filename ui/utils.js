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

// "1.23MiB/s" -> bytes per second, as yt-dlp prints it; 0 if unparseable.
function parseSpeed(text) {
  const m = /^([\d.]+)\s*([KMGT]?i?)B\/s$/i.exec((text || '').trim());
  if (!m) return 0;
  const units = { '': 1, K: 1024, M: 1024 ** 2, G: 1024 ** 3, T: 1024 ** 4 };
  return parseFloat(m[1]) * (units[m[2].replace(/i/i, '').toUpperCase()] || 1);
}

function formatSpeed(bps) {
  const units = ['B/s', 'KiB/s', 'MiB/s', 'GiB/s'];
  let i = 0;
  while (bps >= 1024 && i < units.length - 1) { bps /= 1024; i++; }
  return `${bps.toFixed(i ? 1 : 0)} ${units[i]}`;
}

// A close-enough render of a yt-dlp output template, for the example shown
// under the Filename field. Covers what people actually type: %(field)s,
// widths and precisions (%(playlist_index)03d, %(title).40s), alternatives
// (%(release_date,upload_date)s), dotted lookups, and %% for a literal
// percent. Missing fields become NA, as yt-dlp does. It is not the real
// thing — yt-dlp's own syntax has conversions and filters besides — so the
// UI calls it an example, not a guarantee.
const TEMPLATE_FIELD_RE = /%\((?<names>[\w.,: ]+)\)(?<spec>[-+ #0]*\d*(?:\.\d+)?)(?<type>[sdjqBUDSl])?/g;

function renderOutputTemplate(template, fields) {
  if (!template) return '';
  return String(template).replace(/%%/g, '\u0000').replace(
    TEMPLATE_FIELD_RE,
    (whole, names, spec, type) => {
      let value;
      for (const name of names.split(',').map(n => n.trim()).filter(Boolean)) {
        value = name.split('.').reduce((o, k) => (o == null ? undefined : o[k]), fields);
        if (value !== undefined && value !== null && value !== '') break;
      }
      if (value === undefined || value === null || value === '') return 'NA';
      let text = String(value);
      const precision = /\.(\d+)/.exec(spec);
      if (precision && type !== 'd') text = text.slice(0, Number(precision[1]));
      const width = /^[-+ #0]*(\d+)/.exec(spec);
      if (width) {
        const pad = spec.includes('0') && !spec.includes('-') ? '0' : ' ';
        const n = Number(width[1]);
        text = spec.includes('-') ? text.padEnd(n, ' ') : text.padStart(n, pad);
      }
      return text;
    }
  ).replace(/\u0000/g, '%');
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { getPath, setPath, deepMerge, settingsFingerprint, parseSpeed, formatSpeed, renderOutputTemplate };
}
