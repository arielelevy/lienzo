import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { profiles, existingEndpoint } from '../lienzo/browser_profiles.mjs';

test('perfiles: sólo nombres e IDs, sin datos privados ni rutas arbitrarias', () => {
  const root = mkdtempSync(join(tmpdir(), 'lienzo-profiles-'));
  try {
    assert.deepEqual(profiles(root), []);
    writeFileSync(join(root, 'Local State'), JSON.stringify({profile: {info_cache: {
      Default: {name: 'globant.com', user_name: 'privado', gaia_id: 'secreto'},
      'Profile 1': {name: 'Ariel'}, '../escape': {name: 'No'},
    }}}));
    assert.deepEqual(profiles(root), [{id: 'Default', name: 'globant.com'}, {id: 'Profile 1', name: 'Ariel'}]);
  } finally { rmSync(root, {recursive: true}); }
});

test('conexión habitual: sólo loopback y ruta publicada por Chrome', () => {
  const root = mkdtempSync(join(tmpdir(), 'lienzo-endpoint-'));
  try {
    assert.throws(() => existingEndpoint(root), /chrome:\/\/inspect/);
    for (const value of ['0\n/devtools/browser/a', '65536\n/devtools/browser/a', '123x\n/devtools/browser/a', '123\n//evil.example', '123\n/devtools/browser/a?x=1']) {
      writeFileSync(join(root, 'DevToolsActivePort'), value);
      assert.throws(() => existingEndpoint(root), /inválida/);
    }
    writeFileSync(join(root, 'DevToolsActivePort'), '9222\r\n/devtools/browser/test-id\r\n');
    assert.equal(existingEndpoint(root), 'ws://127.0.0.1:9222/devtools/browser/test-id');
  } finally { rmSync(root, {recursive: true}); }
});
