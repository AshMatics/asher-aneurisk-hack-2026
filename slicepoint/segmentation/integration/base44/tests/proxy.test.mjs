import test from 'node:test';
import assert from 'node:assert/strict';
import { compareProxy } from '../src/server/slicepoint/compare-proxy.server.js';

const secrets = { SLICEPOINT_API_URL: 'https://example.trycloudflare.com',
                  SLICEPOINT_API_TOKEN: 'a-server-only-token-at-least-32-characters' };
const context = { getBase44: () => ({ auth: { me: async () => ({ id: 'test-user' }) } }) };
function request() {
  const form = new FormData();
  form.append('ct', new Blob(['ct']), 'ct.nii.gz');
  form.append('vendor_mask', new Blob(['mask']), 'mask.nii.gz');
  return new Request('https://app.example/api/segmentation/compare', { method: 'POST', body: form });
}

test('rejects signed-out callers before reaching inference service', async () => {
  let called = false;
  const result = await compareProxy({ request: request(), secrets,
    context: { getBase44: () => ({ auth: { me: async () => { throw Error('signed out'); } } }) },
    fetchImpl: async () => { called = true; } });
  assert.equal(result.status, 401); assert.equal(called, false);
});

test('keeps API secret in server-to-server headers and returns image JSON', async () => {
  const result = await compareProxy({ request: request(), context, secrets,
    fetchImpl: async (url, options) => {
      assert.equal(url.href, 'https://example.trycloudflare.com/v1/compare');
      assert.equal(options.headers.Authorization, `Bearer ${secrets.SLICEPOINT_API_TOKEN}`);
      assert.equal(options.body.get('response_format'), 'json');
      assert.equal(options.redirect, 'error');
      return Response.json({ metrics: { dice: .91 }, image: { data_url: 'data:image/png;base64,fixture' } });
    } });
  assert.equal(result.status, 200);
  assert.equal(result.headers.get('cache-control'), 'no-store');
  const body = await result.text();
  assert.ok(body.includes('data:image/png')); assert.ok(!body.includes(secrets.SLICEPOINT_API_TOKEN));
});

test('rejects missing files before upstream call', async () => {
  const req = new Request('https://app.example', { method: 'POST', body: new FormData() });
  const result = await compareProxy({ request: req, context, secrets,
    fetchImpl: async () => { throw Error('must not call'); } });
  assert.equal(result.status, 422);
});

test('refuses HTTP endpoints and weak secrets', async () => {
  for (const invalid of [{ ...secrets, SLICEPOINT_API_URL: 'http://example.com' },
                          { ...secrets, SLICEPOINT_API_TOKEN: 'short' }]) {
    const result = await compareProxy({ request: request(), context, secrets: invalid });
    assert.equal(result.status, 503);
  }
});

test('does not expose upstream errors or credentials to the browser', async () => {
  const result = await compareProxy({ request: request(), context, secrets,
    fetchImpl: async () => new Response('private debug stack', { status: 401 }) });
  assert.equal(result.status, 502);
  assert.ok(!(await result.text()).includes('private debug stack'));
});
