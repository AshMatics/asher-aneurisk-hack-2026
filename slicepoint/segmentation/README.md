# SlicePoint: pretrained 3D aorta segmentation

This is a runnable first implementation, not a newly trained or validated model.
It wraps **TotalSegmentator 2.11.0**, `task=total`, `roi_subset=["aorta"]`.
The model generates a 3D binary aorta mask on the original CT grid. Default inference
uses the model's 1.5 mm processing resolution; `--fast` uses a 3 mm preview mode.
Weights download automatically on first inference and persist in `TOTALSEG_HOME_DIR`.
The aorta ROI workflow also downloads a 6 mm localization model before the selected
3 mm or 1.5 mm segmentation model.
The version is deliberately pinned to the API inspected for this implementation.

## Scope and data

This package adds a pretrained aorta baseline, mask comparison, cohort evaluation,
and an authenticated local API. The hackathon starter predicts diameter from
embeddings; this extension instead processes aligned 3D NIfTI CT volumes and masks.
It is independent of the Base44 frontend.

Vendor tables contain reported Dice scores, not vendor segmentation masks. Supply
vendor masks explicitly for direct model/vendor agreement. A reference mask used
as an API fixture must not be described as a vendor prediction. Agreement alone
does not establish clinical correctness.

Data keeps its source licenses; consult the download's CREDITS.md. Never commit
signed download URLs, CTs, masks, model weights, generated patient images or keys.

## Install

Use Python 3.10–3.12 (3.12 recommended for the GPU package).

```bash
cd slicepoint/segmentation
python3.12 -m venv .venv
source .venv/bin/activate
pip install '.[model,test]'
pytest tests -q
```

## Download the event data

Set `AZURE_DATA_SAS_URL` privately in the environment to the supplied kickoff URL.
Do not put the signed URL in source control. Container URLs with a folder prefix
such as `/container/students?…` are supported. Downloads stream to disk; local
SHA-256 hashes are recorded without signed URLs. ZIPs are retained under `_archives`.
Archive hashes record downloaded bytes. `scripts/inspect_data.py` separately
verifies the table files against the sponsor's manifest and checks CT/mask grids.

```bash
slicepoint-model download --output data --hospital hospital_a
# Download just the small practice tables:
slicepoint-model download --output data --tables-only
# Sunday data, when released:
slicepoint-model download --output data --release sunday
```

Review the extracted layout before inference. The expected hospital directory is:

```text
data/practice/hospital_a/
  features.parquet
  predictions.parquet
  images/<case_id>.nii.gz
  masks/<case_id>_aorta.nii.gz
```

Some archives may extract hospitals directly under `data/`. If so, point
`--hospital` at that location or move the extracted image/mask directories beside
the matching hospital tables. The downloaded practice archives have been verified to use the `practice/hospital_x/` layout.

## Check downloaded data

```bash
python scripts/inspect_data.py --data data/practice --output outputs/data-inventory.json
```

## Run one case or a hospital

```bash
slicepoint-model predict --ct data/practice/hospital_a/images/CASE.nii.gz \
  --reference data/practice/hospital_a/masks/CASE_aorta.nii.gz --output outputs/CASE

# First smoke run, then omit --limit for the hospital:
slicepoint-model evaluate --hospital data/practice/hospital_a --output outputs/hospital_a --limit 2

# Optional vendor binary masks, named CASE_aorta.nii.gz:
slicepoint-model evaluate --hospital data/practice/hospital_a \
  --vendor-masks data/vendor_masks/hospital_a --output outputs/with_vendor_masks

# Evaluate existing masks without loading the model:
slicepoint-model compare --prediction outputs/CASE/aorta.nii.gz \
  --reference data/practice/hospital_a/masks/CASE_aorta.nii.gz
```

Each successful case records model version, settings, timing and CT/mask hashes.
`cases.csv` includes failures rather than silently excluding them. `summary.json`
includes 3D Dice, case counts, subgroup means and a patient-cluster bootstrap CI
for the mean paired Dice difference against reported vendor scores. Missing patient
IDs fall back to case IDs; incomplete identifiers can therefore understate dependence.
Thin subgroups limit conclusions. The actual event CREDITS.md identifies the
TotalSegmentator dataset and `total`-task segmentations. This same-family baseline
is not an independent external validation, and case-level pretraining overlap is
unknown. Do not use it to claim superiority over a vendor model.

Scoring rejects different shapes, affines and nonbinary masks; it does not silently
resample or treat a multiclass volume as a binary aorta. HD95 uses pooled surface
voxel distances in millimetres, supports orthogonal anisotropic grids, and is null
for one empty mask or a sheared affine. Both-empty Dice is 1 and flagged explicitly.
Check lumen vs outer-wall annotations and aortic extent before interpreting Dice;
this anatomical mismatch can dominate the score. There is no validated diameter
or AAA diagnostic estimator in this implementation.

## Run on a Nebius GPU VM

Use a Nebius GPU compute VM with working NVIDIA drivers and NVIDIA Container
Toolkit. This container is intended for Compute/Kubernetes, **not an assumed
Token Factory deployment**. Token Factory dedicated endpoints serve supported
model templates; generic arbitrary-container support for TotalSegmentator has not
been established. A Token Factory API key alone is insufficient for this service.

On the GPU VM, build and first run the two-case command above inside the container:

```bash
docker build -t slicepoint-model .
docker volume create slicepoint-weights

docker run --rm --gpus all --ipc=host \
  -v slicepoint-weights:/models \
  -v "$PWD/data:/data:ro" -v "$PWD/outputs:/outputs" \
  slicepoint-model slicepoint-model evaluate \
  --hospital /data/practice/hospital_a --output /outputs/smoke --limit 2
```

Allow outbound HTTPS for first-run pretrained-weight downloads. For reproducible
runs retain the weights volume, run manifests, image digest and the container's
`/app/installed-versions.txt`. The Docker image has not been built in this workspace.

For serving, set `SLICEPOINT_API_TOKEN` to a long random secret in the environment:

```bash
docker run --rm --gpus all --ipc=host \
  -p 127.0.0.1:8000:8000 -e SLICEPOINT_API_TOKEN \
  -v slicepoint-weights:/models slicepoint-model

curl --fail-with-body http://127.0.0.1:8000/v1/segment \
  -H "Authorization: Bearer $SLICEPOINT_API_TOKEN" \
  -F 'ct=@data/practice/hospital_a/images/CASE.nii.gz' -o prediction.zip
```

`prediction.zip` contains `aorta.nii.gz` and `result.json`. Uploads are temporary
and removed after response delivery. The API accepts one job at a time (busy =
503), requires a bearer token, and defaults to 64 MiB compressed upload and
100 million voxels per volume. Run one worker per GPU. `/healthz` is liveness,
not model readiness. Startup does not download weights; warm up using a real test
case before connecting a frontend. Long scans may exceed HTTP proxy timeouts;
use batch mode initially and a persistent job queue for a production frontend.

Keep the service private; expose it through an HTTPS gateway with request limits
if needed. Base44 should call it through a server-side function so the shared
secret stays out of browser JavaScript. The comparison contract is multipart `ct` and `vendor_mask` uploads to
`/v1/compare`, returning metrics and a PNG. See [LOCAL_API.md](LOCAL_API.md).

## Verification and limitations

33 synthetic Python tests cover scoring, grid alignment, empty masks, thresholds,
images, authorization, upload limits, rate limits and concurrency. Five Node proxy
checks cover the server integration helper. Real pretrained CPU smoke inference
has been run on two event volumes; this is not a full-cohort accuracy estimate.
The event data and this baseline share the TotalSegmentator family, so this is not
independent vendor validation. Docker and Nebius deployment have not been verified.

```bash
pytest tests -q
node integration/base44/tests/proxy.test.mjs
```

The optional Base44 integration is an example for server-side authenticated
forwarding. Its route adapter uses Cloudflare's environment import; deployments
on Base44 must adapt secret access to their supported server runtime. It is not an
export of the hosted app. The current built-in PNG demonstration is described in
[DEMO_COMPARISON.md](DEMO_COMPARISON.md) and uses a preset score without inference.

Model source: [TotalSegmentator 2.11.0](https://github.com/wasserth/TotalSegmentator/tree/v2.11.0).
Model weights and datasets retain their own licenses; this repository's MIT license
covers the added source code.
