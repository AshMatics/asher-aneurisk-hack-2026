// Server-only helper. Never import this module into a React component.
export async function compareProxy({ request, context, secrets, fetchImpl = fetch }) {
  let user;
  try {
    user = await context.getBase44().auth.me();
  } catch {
    return Response.json({ error: 'Sign in to compare segmentations.' }, { status: 401 });
  }
  if (!user?.id) return Response.json({ error: 'Sign in required.' }, { status: 401 });
  const token = secrets.SLICEPOINT_API_TOKEN;
  let endpoint;
  try {
    endpoint = new URL('/v1/compare', secrets.SLICEPOINT_API_URL);
    if (endpoint.protocol !== 'https:' || endpoint.username || endpoint.password || !token || token.length < 32) {
      throw new Error('Invalid server configuration');
    }
  } catch {
    return Response.json({ error: 'Comparison service is not configured.' }, { status: 503 });
  }
  // Stay below the hosting platform's request and memory limits.
  const max = 50 * 1024 * 1024;
  const size = Number(request.headers.get('content-length') || 0);
  if (!Number.isFinite(size) || size < 0 || size > max + 1024 * 1024) {
    return Response.json({ error: 'Upload exceeds the 50 MiB limit.' }, { status: 413 });
  }
  let input;
  try {
    input = await request.formData();
  } catch {
    return Response.json({ error: 'Upload CT and vendor_mask as multipart files.' }, { status: 400 });
  }
  const ct = input.get('ct');
  const vendor = input.get('vendor_mask');
  if (!(ct instanceof Blob) || !(vendor instanceof Blob)) {
    return Response.json({ error: 'Both CT and vendor mask files are required.' }, { status: 422 });
  }
  if (ct.size + vendor.size > max) {
    return Response.json({ error: 'Combined files exceed the 50 MiB limit.' }, { status: 413 });
  }
  const body = new FormData();
  body.append('ct', ct, 'ct.nii.gz');
  body.append('vendor_mask', vendor, 'vendor.nii.gz');
  body.append('response_format', 'json');
  try {
    const upstream = await fetchImpl(endpoint, {
      method: 'POST', headers: { Authorization: `Bearer ${token}` }, body,
      redirect: 'error', signal: AbortSignal.timeout(110_000),
    });
    if (!upstream.ok) {
      const messages = {
        401: 'Comparison service credentials need updating.',
        413: 'CT and mask files are too large.',
        422: 'The CT and binary vendor mask must have matching 3D grids.',
        429: 'Too many comparisons. Wait a minute and retry.',
        503: 'The comparison model is busy. Retry shortly.',
      };
      return Response.json({ error: messages[upstream.status] || 'Comparison failed. Try again.' },
                           { status: upstream.status === 401 ? 502 : upstream.status });
    }
    return new Response(upstream.body, {
      headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
    });
  } catch {
    return Response.json({ error: 'Your computer’s comparison service is unavailable or timed out.' }, { status: 502 });
  }
}
