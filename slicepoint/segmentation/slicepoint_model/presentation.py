"""Agreement summaries and a CT/vendor/model contour image."""
from pathlib import Path

import nibabel as nib
import numpy as np

from .core import load_volume, require_same_grid


def agreement_assessment(metrics):
    dice = float(metrics['dice'])
    if not np.isfinite(dice) or not 0 <= dice <= 1:
        raise ValueError('Dice must be finite and between zero and one')
    if metrics.get('empty_prediction') or metrics.get('empty_reference'):
        status, priority = 'empty_mask_review', 'high'
        message = 'Review required: at least one aorta mask is empty.'
    elif dice > 0.9:
        status, priority = 'high_agreement', 'low'
        message = 'High agreement: the vendor mask closely matches the comparison model.'
    elif dice >= 0.7:
        status, priority = 'review_with_caution', 'medium'
        message = 'Review with caution: the segmentations differ; inspect the overlay.'
    else:
        status, priority = 'low_agreement', 'high'
        message = 'Low agreement: the vendor segmentation needs review.'
    return {
        'status': status, 'review_priority': priority, 'message': message,
        'dice_percent': round(dice * 100, 2),
        'clinical_correctness_established': False,
        'interpretation': 'Dice measures agreement between masks. High agreement does not prove '
            'either mask is correct; low agreement does not establish which model is wrong.',
        'thresholds': {'high_agreement': '> 0.9', 'review_with_caution': '0.7 through 0.9',
                       'low_agreement': '< 0.7'},
    }


def render_comparison(ct_path: Path, vendor_path: Path, prediction_path: Path,
                      destination: Path, metrics, assessment):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    ct, _ = load_volume(ct_path)
    vendor, _ = load_volume(vendor_path, mask=True)
    prediction, _ = load_volume(prediction_path, mask=True)
    require_same_grid(ct, vendor)
    require_same_grid(ct, prediction)
    # Reorient only for display, applying the same transform to all aligned volumes.
    ct, vendor, prediction = [nib.as_closest_canonical(image) for image in (ct, vendor, prediction)]
    c = ct.get_fdata(dtype=np.float32)
    v = vendor.get_fdata(dtype=np.float32) > 0
    p = prediction.get_fdata(dtype=np.float32) > 0
    union = v | p
    z = int(np.argmax(union.sum(axis=(0, 1)))) if union.any() else c.shape[2] // 2
    locations = np.argwhere(union[:, :, z])
    if len(locations):
        spacing = np.linalg.norm(ct.affine[:3, :3], axis=0)
        margin = np.maximum(np.ceil(55 / spacing[:2]).astype(int), 12)
        lo = np.maximum(locations.min(axis=0) - margin, 0)
        hi = np.minimum(locations.max(axis=0) + margin + 1, c.shape[:2])
    else:
        lo, hi = (0, 0), c.shape[:2]
    region = (slice(lo[0], hi[0]), slice(lo[1], hi[1]), z)
    spacing = np.linalg.norm(ct.affine[:3, :3], axis=0)
    fig, axes = plt.subplots(1, 3, figsize=(11, 4.4), facecolor='#101821')
    try:
        for ax, title in zip(axes, ['CT slice', 'Vendor segmentation', 'Comparison model']):
            ax.imshow(c[region].T, cmap='gray', vmin=-150, vmax=300, origin='lower',
                      aspect=spacing[1] / spacing[0])
            ax.set_title(title, color='white', fontsize=12)
            ax.axis('off')
        if v[region].any():
            axes[1].contour(v[region].T, levels=[.5], colors=['#39dc9c'], linewidths=1.6)
        if p[region].any():
            axes[2].contour(p[region].T, levels=[.5], colors=['#ef8edf'], linewidths=1.6)
        fig.suptitle('Aorta segmentation agreement', color='white', fontsize=16)
        fig.text(.5, .115, f'3D Dice {metrics["dice"]:.3f} ({assessment["dice_percent"]:.2f}%)',
                 ha='center', color='white', fontsize=12)
        fig.text(.5, .07, assessment['message'], ha='center', color='#cbd5e1', fontsize=10)
        fig.text(.5, .025, 'One selected axial slice shown. Agreement does not establish clinical correctness.',
                 ha='center', color='#a6b0bf', fontsize=9)
        fig.subplots_adjust(top=.82, bottom=.19, wspace=.04)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(destination, dpi=150, facecolor=fig.get_facecolor())
    finally:
        plt.close(fig)
    return {'plane': 'axial', 'canonical_slice_index': z,
            'selection': 'Largest union area of vendor and predicted aorta masks',
            'ct_window_hu': [-150, 300], 'score_dimension': '3D'}
