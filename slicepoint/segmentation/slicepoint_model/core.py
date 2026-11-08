from __future__ import annotations

import hashlib
import importlib.metadata
import time
from pathlib import Path

import nibabel as nib
import numpy as np
from scipy.ndimage import binary_erosion, distance_transform_edt


def load_volume(path: Path, *, mask=False):
    img = nib.load(path)
    if len(img.shape) != 3 or min(img.shape) < 1:
        raise ValueError("Expected a nonempty 3D NIfTI volume")
    if not np.isfinite(img.affine).all() or abs(np.linalg.det(img.affine[:3, :3])) < 1e-10:
        raise ValueError("Invalid image affine")
    # NIfTI without declared units is assumed to follow the dataset's mm convention.
    if img.header.get_xyzt_units()[0] not in ('mm', 'unknown'):
        raise ValueError("Spatial units must be millimetres")
    data = img.get_fdata(dtype=np.float32)
    if not np.isfinite(data).all():
        raise ValueError("Volume contains nonfinite voxels")
    if mask and not np.isin(data, [0, 1]).all():
        raise ValueError("Mask must be binary 0/1; explicitly select the aorta label first")
    return img, data.astype(bool) if mask else data


def require_same_grid(first, second):
    if first.shape != second.shape or not np.allclose(first.affine, second.affine, atol=1e-4, rtol=0):
        raise ValueError("Masks must share shape and affine; resample explicitly before evaluation")


def compare_masks(prediction: Path, reference: Path):
    pimg, p = load_volume(prediction, mask=True)
    rimg, r = load_volume(reference, mask=True)
    require_same_grid(pimg, rimg)
    npred, nref = int(p.sum()), int(r.sum())
    intersection = int(np.logical_and(p, r).sum())
    union = npred + nref - intersection
    voxel_ml = abs(float(np.linalg.det(pimg.affine[:3, :3]))) / 1000
    result = {
        "dice": 2 * intersection / (npred + nref) if npred + nref else 1.0,
        "iou": intersection / union if union else 1.0,
        "prediction_volume_ml": npred * voxel_ml,
        "reference_volume_ml": nref * voxel_ml,
        "hd95_mm": None,
        "empty_prediction": npred == 0,
        "empty_reference": nref == 0,
    }
    # Distance transforms assume orthogonal voxel axes. Do not silently mis-score shear.
    axes = pimg.affine[:3, :3]
    spacing = np.linalg.norm(axes, axis=0)
    orthogonal = np.allclose((axes / spacing).T @ (axes / spacing), np.eye(3), atol=1e-5)
    if npred and nref and orthogonal:
        ps = p ^ binary_erosion(p)
        rs = r ^ binary_erosion(r)
        distances = np.concatenate([
            distance_transform_edt(~rs, sampling=spacing)[ps],
            distance_transform_edt(~ps, sampling=spacing)[rs],
        ])
        result["hd95_mm"] = float(np.percentile(distances, 95))
        result["hd95_status"] = "ok"
    elif not union:
        result["hd95_mm"] = 0.0
        result["hd95_status"] = "both_empty"
    else:
        result["hd95_status"] = "empty_mask" if not (npred and nref) else "sheared_grid"
    return result


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def predict(ct: Path, output_dir: Path, *, fast=False, device='gpu'):
    load_volume(ct)
    import torch
    from totalsegmentator.python_api import totalsegmentator

    if device.startswith('gpu') and not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; use --device cpu explicitly for a slow CPU run")
    from totalsegmentator.config import get_totalseg_dir, setup_totalseg, set_config_key
    get_totalseg_dir().mkdir(parents=True, exist_ok=True)
    setup_totalseg()
    set_config_key('send_usage_stats', False)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    totalsegmentator(input=ct, output=output_dir, task='total',
                    roi_subset=['aorta'], fast=fast, device=device, quiet=True)
    mask = output_dir / 'aorta.nii.gz'
    mimg, _ = load_volume(mask, mask=True)
    cimg = nib.load(ct)
    require_same_grid(cimg, mimg)
    return mask, {
        'model': 'TotalSegmentator',
        'version': importlib.metadata.version('TotalSegmentator'),
        'task': 'total', 'roi': 'aorta', 'fast': fast, 'device': device,
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'input_sha256': sha256(ct), 'mask_sha256': sha256(mask),
    }
