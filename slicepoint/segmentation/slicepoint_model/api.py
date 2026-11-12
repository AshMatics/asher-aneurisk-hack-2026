"""Private single-GPU segmentation and vendor-mask comparison API."""
import base64
import json
import math
import os
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Literal

import nibabel as nib
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from .core import compare_masks, load_volume, predict, require_same_grid
from .presentation import agreement_assessment, render_comparison
from .security import SecurityMiddleware, valid_token

app = FastAPI(title='SlicePoint aorta segmentation', version='0.3.1',
              docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SecurityMiddleware)
lock = threading.Lock()


def authorize(authorization: str = Header(default='')):
    allowed = valid_token(authorization.encode())
    if allowed is None:
        raise HTTPException(503, 'Service authentication is not configured')
    if not allowed:
        raise HTTPException(401, 'Invalid bearer token')


@app.get('/healthz')
def health():
    return {'status': 'alive', 'note': 'Liveness only; weights are loaded during inference'}


async def save_upload(upload: UploadFile, path: Path, total_bytes=0):
    size = total_bytes
    with path.open('wb') as stream:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > int(os.environ.get('MAX_UPLOAD_MB', '64')) * 1024 * 1024:
                raise HTTPException(413, 'Combined volume uploads exceed the upload limit')
            stream.write(chunk)
    try:
        image = nib.load(path)
        if len(image.shape) != 3 or math.prod(image.shape) > 100_000_000:
            raise ValueError('Volume shape exceeds service limits')
    except Exception:
        raise HTTPException(422, 'Expected a 3D NIfTI .nii.gz volume within service limits')
    return size


async def infer(path, output):
    try:
        return await run_in_threadpool(
            predict, path, output, device=os.environ.get('SLICEPOINT_DEVICE', 'gpu'),
            fast=os.environ.get('SLICEPOINT_FAST', '0') == '1')
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception:
        raise HTTPException(500, 'Segmentation failed; check model weights and GPU configuration')


def acquire():
    if not lock.acquire(blocking=False):
        raise HTTPException(503, 'Model is busy; retry later', headers={'Retry-After': '30'})


def send_file(path, folder, *, media_type, filename):
    return FileResponse(path, media_type=media_type, filename=filename,
                        background=BackgroundTask(shutil.rmtree, folder))


@app.post('/v1/segment', dependencies=[Depends(authorize)])
async def segment(ct: UploadFile = File(...)):
    acquire()
    folder = Path(tempfile.mkdtemp(prefix='slicepoint-'))
    handed_off = False
    try:
        path = folder / 'ct.nii.gz'
        await save_upload(ct, path)
        mask, metadata = await infer(path, folder / 'output')
        bundle = folder / 'segmentation.zip'
        with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(mask, 'aorta.nii.gz')
            archive.writestr('result.json', json.dumps(metadata, indent=2))
        response = send_file(bundle, folder, media_type='application/zip', filename='segmentation.zip')
        handed_off = True
        return response
    finally:
        await ct.close()
        lock.release()
        if not handed_off:
            shutil.rmtree(folder, ignore_errors=True)


@app.post('/v1/compare', dependencies=[Depends(authorize)])
async def compare(ct: UploadFile = File(...), vendor_mask: UploadFile = File(...),
                  response_format: Literal['json', 'zip', 'image'] = Form(default='json'),
                  include_mask: bool = Form(default=False)):
    """CT + vendor binary aorta mask -> 3D agreement, human summary and PNG."""
    acquire()
    folder = Path(tempfile.mkdtemp(prefix='slicepoint-'))
    handed_off = False
    try:
        ct_path, vendor_path = folder / 'ct.nii.gz', folder / 'vendor.nii.gz'
        total = await save_upload(ct, ct_path)
        await save_upload(vendor_mask, vendor_path, total)
        # The vendor mask is checked before inference and never passed into the model.
        try:
            cimg, _ = await run_in_threadpool(load_volume, ct_path)
            vimg, _ = await run_in_threadpool(load_volume, vendor_path, mask=True)
            require_same_grid(cimg, vimg)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        prediction, provenance = await infer(ct_path, folder / 'output')
        try:
            metrics = await run_in_threadpool(compare_masks, prediction, vendor_path)
            assessment = agreement_assessment(metrics)
            png = folder / 'comparison.png'
            display = await run_in_threadpool(render_comparison, ct_path, vendor_path,
                                             prediction, png, metrics, assessment)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        result = {
            'schema_version': '1.0', 'comparison_type': 'model_vs_vendor_mask_agreement',
            'metrics': metrics, 'assessment': assessment, 'model': provenance,
            'display': display,
            'limitation': 'Comparison-model errors or shared training data can affect agreement. '
                          'The vendor mask is a comparison input, not independently verified ground truth.',
        }
        if response_format == 'json':
            result['image'] = {
                'media_type': 'image/png',
                'data_url': 'data:image/png;base64,' + base64.b64encode(png.read_bytes()).decode('ascii'),
            }
            if include_mask:
                result['predicted_mask'] = {
                    'media_type': 'application/gzip', 'filename': 'aorta.nii.gz',
                    'base64': base64.b64encode(prediction.read_bytes()).decode('ascii'),
                }
            return result
        if response_format == 'image':
            response = send_file(png, folder, media_type='image/png', filename='comparison.png')
            response.headers['X-Dice-Score'] = str(metrics['dice'])
            response.headers['X-Agreement-Status'] = assessment['status']
        else:
            bundle = folder / 'comparison.zip'
            with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.write(prediction, 'aorta.nii.gz')
                archive.write(png, 'comparison.png')
                archive.writestr('result.json', json.dumps(result, indent=2))
            response = send_file(bundle, folder, media_type='application/zip', filename='comparison.zip')
        handed_off = True
        return response
    finally:
        await ct.close()
        await vendor_mask.close()
        lock.release()
        if not handed_off:
            shutil.rmtree(folder, ignore_errors=True)
