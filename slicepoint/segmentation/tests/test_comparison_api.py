import base64
import io
import json
import zipfile

import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from slicepoint_model import api
from slicepoint_model.presentation import agreement_assessment


def nifti(tmp_path, name, data, affine=None):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.asarray(data, dtype=np.uint8),
                           np.eye(4) if affine is None else affine), path)
    return path


@pytest.mark.parametrize('dice,status', [(1., 'high_agreement'), (.900001, 'high_agreement'),
    (.9, 'review_with_caution'), (.7, 'review_with_caution'), (.69999, 'low_agreement'),
    (0., 'low_agreement')])
def test_exact_threshold_boundaries(dice, status):
    assessment = agreement_assessment({'dice': dice})
    assert assessment['status'] == status
    assert assessment['clinical_correctness_established'] is False


def test_empty_agreement_never_says_high():
    assert agreement_assessment({'dice': 1., 'empty_prediction': True,
                                 'empty_reference': True})['status'] == 'empty_mask_review'


@pytest.mark.parametrize('score', [float('nan'), float('inf'), -1, 1.1])
def test_invalid_dice_rejected(score):
    with pytest.raises(ValueError):
        agreement_assessment({'dice': score})


@pytest.fixture
def comparison(tmp_path, monkeypatch):
    monkeypatch.setenv('SLICEPOINT_API_TOKEN', 'test-token-at-least-32-characters-for-local-verification')
    v = np.zeros((20, 20, 12), dtype=np.uint8)
    v[8:12, 8:12, 2:10] = 1
    image = nifti(tmp_path, 'ct.nii.gz', np.full(v.shape, 50))
    vendor = nifti(tmp_path, 'vendor.nii.gz', v)
    seen = []
    def fake_predict(ct, output, **kwargs):
        # Only the CT, output path and inference options reach the prediction model.
        seen.append((ct, kwargs))
        return vendor, {'model': 'test fixture'}
    monkeypatch.setattr(api, 'predict', fake_predict)
    return TestClient(api.app), image, vendor, seen


def request(client, ct, vendor, **data):
    return client.post('/v1/compare', headers={'Authorization': 'Bearer test-token-at-least-32-characters-for-local-verification'},
                       files={'ct': ('ct.nii.gz', ct.read_bytes()),
                              'vendor_mask': ('vendor.nii.gz', vendor.read_bytes())}, data=data)


def test_json_has_real_png_mask_and_no_clinical_approval(comparison):
    client, ct, vendor, seen = comparison
    response = request(client, ct, vendor, include_mask='true')
    assert response.status_code == 200
    result = response.json()
    assert result['metrics']['dice'] == 1
    assert result['assessment']['status'] == 'high_agreement'
    assert result['assessment']['clinical_correctness_established'] is False
    assert len(seen) == 1 and 'vendor_mask' not in seen[0][1]
    png = base64.b64decode(result['image']['data_url'].split(',', 1)[1])
    with Image.open(io.BytesIO(png)) as image:
        assert image.size == (1650, 660)
        assert image.format == 'PNG'
    assert base64.b64decode(result['predicted_mask']['base64']) == vendor.read_bytes()
    assert not seen[0][0].parent.exists(), 'Temporary uploads should be cleaned after response'


@pytest.mark.parametrize('format', ['zip', 'image'])
def test_file_response_formats(comparison, format):
    client, ct, vendor, _ = comparison
    response = request(client, ct, vendor, response_format=format)
    assert response.status_code == 200
    if format == 'image':
        assert response.headers['content-type'] == 'image/png'
        assert response.headers['x-agreement-status'] == 'high_agreement'
        assert response.content.startswith(b'\x89PNG')
    else:
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            assert set(z.namelist()) == {'aorta.nii.gz', 'comparison.png', 'result.json'}
            assert json.loads(z.read('result.json'))['metrics']['dice'] == 1


def test_grid_mismatch_rejected_before_inference(comparison, tmp_path):
    client, ct, vendor, seen = comparison
    shifted = np.eye(4); shifted[0, 3] = 10
    bad = nifti(tmp_path, 'shifted.nii.gz', np.zeros((20, 20, 12)), shifted)
    response = request(client, ct, bad)
    assert response.status_code == 422
    assert not seen


def test_missing_or_multiclass_vendor_rejected(comparison, tmp_path):
    client, ct, vendor, seen = comparison
    response = client.post('/v1/compare', headers={'Authorization': 'Bearer test-token-at-least-32-characters-for-local-verification'},
                           files={'ct': ('ct.nii.gz', ct.read_bytes())})
    assert response.status_code == 422
    multiclass = nifti(tmp_path, 'multiclass.nii.gz', np.full((20, 20, 12), 2))
    assert request(client, ct, multiclass).status_code == 422
    assert not seen
