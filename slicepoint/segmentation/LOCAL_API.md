# Local comparison API

Run from `slicepoint/segmentation` after installing `.[model,test]` in `.venv`.
For a loopback-only service, set a random `SLICEPOINT_API_TOKEN` of at least 32
characters in your environment, set `SLICEPOINT_DEVICE=cpu` (or `gpu`), and run:

```bash
.venv/bin/python -m uvicorn slicepoint_model.api:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log --no-proxy-headers
```

`POST /v1/compare` requires `Authorization: Bearer <token>` and multipart fields
`ct` and `vendor_mask`, both aligned 3D NIfTI volumes; the mask must be binary 0/1.
JSON includes `metrics`, `assessment`, `image.data_url` (PNG) and model provenance.
Optional `response_format=image` returns PNG; `response_format=zip` returns PNG,
predicted NIfTI and JSON. `POST /v1/segment` accepts CT alone and returns a ZIP.
The vendor mask is never an input to model inference.

| Dice | Human-readable assessment |
| --- | --- |
| Above 0.9 | High agreement |
| 0.7 through 0.9 | Review with caution |
| Below 0.7 | Low agreement; review required |
| Either mask empty | Review required regardless of Dice |

These scores describe agreement, not which model is clinically correct.

Authentication runs before multipart parsing. Default combined upload limit is
64 MiB and each volume is limited to 100 million voxels. Requests are bounded,
rate limited in memory, and inference runs one job at a time. Temporary uploads
are deleted after the response; API documentation routes are disabled. `/healthz`
reports liveness only. First inference downloads weights; warm up before use.

## Optional development tunnel

The Linux helper creates a random API token, binds to loopback, and starts a
Cloudflare Quick Tunnel. Files pass through Cloudflare. Use only data approved for
that provider. Quick Tunnels are temporary development endpoints, not a stable
production deployment or a compliance certification.

```bash
.venv/bin/python scripts/install_cloudflared.py
.venv/bin/python scripts/local_service.py start
.venv/bin/python scripts/local_service.py status
.venv/bin/python scripts/local_service.py stop
```

The helper uses CPU preview mode, a 64 MiB upload cap and six authenticated
requests per minute. Runtime state, logs and the owner-only token are in ignored
`.local/`. No boot startup is configured. Restarting changes the public address.
Rotate the token by stopping, replacing the private secret, and restarting.

For Base44, store `SLICEPOINT_API_URL` and `SLICEPOINT_API_TOKEN` in its encrypted
server-side secrets. Require a signed-in user in the proxy. Never put the token in
React, browser storage, source control or an AI prompt. See `integration/base44`
for a proxy example; adapt its route adapter to the host's secret runtime. The
current demo page uses neither the proxy nor the API.
