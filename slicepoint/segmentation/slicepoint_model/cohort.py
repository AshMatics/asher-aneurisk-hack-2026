import json
from pathlib import Path

import numpy as np
import pandas as pd

from .core import compare_masks, predict


def patient_bootstrap(frame, repeats=1000):
    """CI for the mean paired case delta, resampling whole patient clusters."""
    if frame.empty:
        return None
    groups = [group.delta_dice.to_numpy() for _, group in frame.groupby('patient_id')]
    if len(groups) < 2:
        return None
    rng = np.random.default_rng(0)
    means = [float(np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))]).mean())
             for _ in range(repeats)]
    return [float(x) for x in np.percentile(means, [2.5, 97.5])]


def evaluate(hospital, output, *, vendor_masks=None, fast=False, device='gpu', limit=None):
    hospital, output = Path(hospital), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    features = pd.read_parquet(hospital / 'features.parquet')
    vendor = pd.read_parquet(hospital / 'predictions.parquet')
    if features.case_id.isna().any() or vendor.case_id.isna().any():
        raise ValueError('Missing case IDs in cohort tables')
    frame = features.merge(vendor, on='case_id', how='left', validate='one_to_one')
    rows = []
    for case in frame.head(limit).to_dict('records'):
        cid = str(case['case_id'])
        if not cid or cid in ('.', '..') or '/' in cid or '\\' in cid:
            raise ValueError('Case IDs must be plain filenames')
        row = {key: case.get(key) for key in ('case_id', 'patient_id', 'sex', 'age_band',
                'scanner_vendor', 'contrast_phase', 'slice_thickness_class')}
        row['patient_id'] = row['patient_id'] if pd.notna(row['patient_id']) else cid
        try:
            ct = hospital / 'images' / f'{cid}.nii.gz'
            ref = hospital / 'masks' / f'{cid}_aorta.nii.gz'
            # Check reference before spending GPU time, never pass it into inference.
            from .core import load_volume, require_same_grid
            cimg, _ = load_volume(ct)
            rimg, _ = load_volume(ref, mask=True)
            require_same_grid(cimg, rimg)
            mask, provenance = predict(ct, output / cid, fast=fast, device=device)
            row.update(compare_masks(mask, ref))
            (output / cid / 'provenance.json').write_text(json.dumps(provenance, indent=2))
            baseline = case.get('pred_aorta_dice')
            if pd.notna(baseline) and 0 <= float(baseline) <= 1:
                row['vendor_reported_dice'] = float(baseline)
                row['delta_dice'] = row['dice'] - float(baseline)
            if vendor_masks:
                vm = Path(vendor_masks) / f'{cid}_aorta.nii.gz'
                # Mask agreement is not accuracy; separately score both against reference.
                row['vendor_recomputed_dice'] = compare_masks(vm, ref)['dice']
                row['model_vendor_agreement_dice'] = compare_masks(mask, vm)['dice']
            row['status'] = 'ok'
        except Exception as exc:
            row.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        rows.append(row)
        print(f'{cid}: {row["status"]}')
    results = pd.DataFrame(rows)
    results.to_csv(output / 'cases.csv', index=False)
    ok = results[results.status == 'ok'] if not results.empty else results
    paired = ok.dropna(subset=['delta_dice']) if 'delta_dice' in ok else pd.DataFrame()
    summary = {
        'hospital': hospital.name, 'attempted': len(rows), 'succeeded': len(ok),
        'failed': len(rows) - len(ok), 'paired_cases': len(paired),
        'mean_dice': float(ok.dice.mean()) if len(ok) else None,
        'mean_delta_vs_vendor_reported': float(paired.delta_dice.mean()) if len(paired) else None,
        'paired_delta_patient_bootstrap_95ci': patient_bootstrap(paired),
        'comparison_note': 'Reported vendor scores may use different scoring conventions. '
            'Only recomputation against identical references is a controlled comparison.',
        'annotation_note': 'Confirm whether reference masks label lumen or outer aortic wall, '
            'and whether their anatomical extent matches TotalSegmentator.',
        'pretraining_overlap': 'Event credits identify the TotalSegmentator dataset and total-task segmentations. '
            'This baseline is not an independent external validation; case-level pretraining overlap is unknown.',
        'subgroups': {},
    }
    if len(ok):
        for column in ('sex', 'age_band', 'scanner_vendor', 'contrast_phase', 'slice_thickness_class'):
            summary['subgroups'][column] = [
                {'group': str(key), 'n': len(g), 'mean_dice': float(g.dice.mean())}
                for key, g in ok.groupby(column, dropna=False)]
    (output / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False))
    return summary
