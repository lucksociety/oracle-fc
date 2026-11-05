import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import worker from '../src/worker.js';

test('deployment config preserves the Discord public verification key', async () => {
  const config = fs.readFileSync(new URL('../wrangler.toml', import.meta.url), 'utf8');
  const publicKey = config.match(/^DISCORD_PUBLIC_KEY\s*=\s*"([a-f0-9]{64})"\s*$/m)?.[1];
  assert.ok(publicKey, 'Deploys must include the app public key, not rely on a dashboard-only variable');
  const key = await crypto.subtle.importKey('raw', Buffer.from(publicKey, 'hex'), { name: 'Ed25519' }, false, ['verify']);
  assert.equal(key.type, 'public');
});

test('signed date autocomplete returns choices immediately without network or model work', async () => {
  const kp = await crypto.subtle.generateKey({ name: 'Ed25519' }, true, ['sign', 'verify']);
  const publicKey = Buffer.from(await crypto.subtle.exportKey('raw', kp.publicKey)).toString('hex');
  const body = JSON.stringify({ type: 4, data: { name: 'soccer', options: [{ name: 'date', type: 3, value: '', focused: true }] } });
  const ts = String(Math.floor(Date.now() / 1000));
  const signature = Buffer.from(await crypto.subtle.sign({ name: 'Ed25519' }, kp.privateKey, new TextEncoder().encode(ts + body))).toString('hex');
  const response = await worker.fetch(new Request('https://worker/', { method: 'POST', body, headers: {
    'X-Signature-Ed25519': signature, 'X-Signature-Timestamp': ts,
  } }), { DISCORD_PUBLIC_KEY: publicKey }, { waitUntil() { assert.fail('Autocomplete must not start background work'); } });
  assert.equal(response.status, 200);
  const result = await response.json();
  assert.equal(result.type, 8);
  assert.equal(result.data.choices.length, 9);
  assert.ok(result.data.choices.every(c => /^\d{4}-\d{2}-\d{2}$/.test(c.value)));
});
