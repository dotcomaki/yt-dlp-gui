// Tests for ui/utils.js (getPath/setPath/deepMerge) using Node's built-in
// test runner — no extra dependency needed for a project this size.
// Run with: node --test tests/test_utils.js
const test = require('node:test');
const assert = require('node:assert/strict');
const { getPath, setPath, deepMerge, settingsFingerprint, parseSpeed, formatSpeed } = require('../ui/utils.js');

test('getPath reads a nested value', () => {
  const obj = { audio: { extractAudio: true } };
  assert.equal(getPath(obj, 'audio.extractAudio'), true);
});

test('getPath returns undefined for a missing path without throwing', () => {
  const obj = { audio: {} };
  assert.equal(getPath(obj, 'audio.nonexistent'), undefined);
  assert.equal(getPath({}, 'nothing.here.at.all'), undefined);
});

test('setPath writes a nested value', () => {
  const obj = { audio: { extractAudio: false } };
  setPath(obj, 'audio.extractAudio', true);
  assert.equal(obj.audio.extractAudio, true);
});

test('deepMerge copies matching-type values from source onto target', () => {
  const target = { preset: 'best', audio: { audioFormat: 'mp3' } };
  const source = { preset: '720p', audio: { audioFormat: 'flac' } };
  deepMerge(target, source);
  assert.equal(target.preset, '720p');
  assert.equal(target.audio.audioFormat, 'flac');
});

test('deepMerge ignores keys missing from the saved source (keeps defaults)', () => {
  const target = { preset: 'best', network: { proxy: '' } };
  const source = { preset: '720p' }; // no "network" key at all
  deepMerge(target, source);
  assert.equal(target.preset, '720p');
  assert.deepEqual(target.network, { proxy: '' });
});

test('deepMerge ignores extra keys the current defaults do not have', () => {
  const target = { preset: 'best' };
  const source = { preset: '720p', somethingRemovedInANewerVersion: 'x' };
  deepMerge(target, source);
  assert.deepEqual(target, { preset: '720p' });
});

test('deepMerge ignores a value whose type does not match the default', () => {
  // e.g. a corrupted or hand-edited settings.json shouldn't be able to
  // replace a boolean with a string, etc.
  const target = { debug: { verbose: false } };
  const source = { debug: { verbose: 'yes please' } };
  deepMerge(target, source);
  assert.equal(target.debug.verbose, false);
});

test('deepMerge recurses into nested objects rather than replacing them wholesale', () => {
  const target = { network: { proxy: '', rateLimit: '', forceIpv4: false } };
  const source = { network: { proxy: 'socks5://127.0.0.1:9050' } };
  deepMerge(target, source);
  assert.equal(target.network.proxy, 'socks5://127.0.0.1:9050');
  assert.equal(target.network.rateLimit, ''); // untouched, not wiped out
  assert.equal(target.network.forceIpv4, false);
});

test('deepMerge handles a null or non-object source gracefully', () => {
  const target = { preset: 'best' };
  assert.deepEqual(deepMerge(target, null), { preset: 'best' });
  assert.deepEqual(deepMerge(target, undefined), { preset: 'best' });
  assert.deepEqual(deepMerge(target, 'not an object'), { preset: 'best' });
});

test('settingsFingerprint ignores key order, unknown keys and the password', () => {
  const defaults = { preset: 'best', auth: { username: '', password: '' }, network: { parallel: '2' } };
  const a = settingsFingerprint(defaults, { auth: { password: 'x', username: 'u' }, preset: '720p', bogus: 1 }, '/dl');
  const b = settingsFingerprint(defaults, { preset: '720p', auth: { username: 'u', password: 'other' } }, '/dl');
  assert.equal(a, b);
});

test('settingsFingerprint changes when a setting or the folder changes', () => {
  const defaults = { preset: 'best', network: { parallel: '2' } };
  const base = settingsFingerprint(defaults, { preset: '720p' }, '/dl');
  assert.notEqual(base, settingsFingerprint(defaults, { preset: '480p' }, '/dl'));
  assert.notEqual(base, settingsFingerprint(defaults, { preset: '720p' }, '/other'));
  assert.equal(settingsFingerprint(defaults, {}, ''), settingsFingerprint(defaults, undefined, undefined));
});

test('settingsFingerprint does not mutate the defaults', () => {
  const defaults = { preset: 'best', auth: { password: '' } };
  settingsFingerprint(defaults, { preset: 'audio', auth: { password: 'p' } }, '');
  assert.deepEqual(defaults, { preset: 'best', auth: { password: '' } });
});

test('parseSpeed reads yt-dlp speed strings', () => {
  assert.equal(parseSpeed('1.50MiB/s'), 1.5 * 1024 ** 2);
  assert.equal(parseSpeed('512.00KiB/s'), 512 * 1024);
  assert.equal(parseSpeed('2.00GiB/s'), 2 * 1024 ** 3);
  assert.equal(parseSpeed('900B/s'), 900);
  assert.equal(parseSpeed('Unknown B/s'), 0);
  assert.equal(parseSpeed(''), 0);
  assert.equal(parseSpeed(undefined), 0);
});

test('formatSpeed picks a sensible unit', () => {
  assert.equal(formatSpeed(900), '900 B/s');
  assert.equal(formatSpeed(1.5 * 1024 ** 2), '1.5 MiB/s');
  assert.equal(formatSpeed(3 * 1024 ** 3), '3.0 GiB/s');
  assert.equal(formatSpeed(parseSpeed('1.50MiB/s') + parseSpeed('512.00KiB/s')), '2.0 MiB/s');
});
