import io
import json
import zipfile

import nibabel as nib
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from slicepoint_model.core import compare_masks
from slicepoint_model.download import safe_extract


def save(tmp_path, name, data, affine=None):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.save(nib.Nifti1Image(np.asarray(data, dtype=np.uint8),
                           np.eye(4) if affine is None else affine), path)
    return path


def test_overlap_volume_and_mm_distance(tmp_path):
    p = np.zeros((8, 8, 8)); p[1:3, 1:3, 1:3] = 1
    r = np.zeros_like(p); r[2:4, 1:3, 1:3] = 1
    affine = np.diag([2., 3., 4., 1.])
    result = compare_masks(save(tmp_path, 'p.nii.gz', p, affine), save(tmp_path, 'r.nii.gz', r, affine))
    assert result['dice'] == .5
    assert result['iou'] == pytest.approx(1/3)
    assert result['prediction_volume_ml'] == pytest.approx(.192)
    assert result['hd95_mm'] == 2


@pytest.mark.parametrize('empty_reference', [True, False])
def test_empty_masks(tmp_path, empty_reference):
    p = np.zeros((3, 3, 3)); r = p.copy()
    if not empty_reference:
        r[1, 1, 1] = 1
    result = compare_masks(save(tmp_path, 'p.nii.gz', p), save(tmp_path, 'r.nii.gz', r))
    assert result['dice'] == int(empty_reference)
    assert result['hd95_mm'] == (0 if empty_reference else None)


def test_affine_mismatch_rejected(tmp_path):
    p = np.ones((3, 3, 3)); affine = np.eye(4); affine[0, 3] = 10
    with pytest.raises(ValueError, match='affine'):
        compare_masks(save(tmp_path, 'p.nii.gz', p), save(tmp_path, 'r.nii.gz', p, affine))


def test_multiclass_mask_rejected(tmp_path):
    with pytest.raises(ValueError, match='binary'):
        compare_masks(save(tmp_path, 'p.nii.gz', np.full((3, 3, 3), 2)),
                      save(tmp_path, 'r.nii.gz', np.ones((3, 3, 3))))


def test_sheared_grid_does_not_claim_mm_distance(tmp_path):
    affine = np.eye(4); affine[0, 1] = .4
    p = save(tmp_path, 'p.nii.gz', np.ones((3, 3, 3)), affine)
    assert compare_masks(p, p)['hd95_status'] == 'sheared_grid'


def test_zip_traversal_rejected(tmp_path):
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('../escaped.txt', 'bad')
    with pytest.raises(ValueError, match='Unsafe'):
        safe_extract(archive, tmp_path / 'data')
    assert not (tmp_path / 'escaped.txt').exists()


def test_cohort_pairs_vendor_scores_and_reports_failure(tmp_path, monkeypatch):
    from slicepoint_model import cohort
    hospital = tmp_path / 'hospital_a'; hospital.mkdir()
    pd.DataFrame({'case_id': ['one', 'missing'], 'patient_id': ['p1', 'p2']}).to_parquet(hospital / 'features.parquet')
    pd.DataFrame({'case_id': ['one', 'missing'], 'pred_aorta_dice': [.7, .9]}).to_parquet(hospital / 'predictions.parquet')
    save(hospital, 'images/one.nii.gz', np.ones((3, 3, 3)))
    ref = save(hospital, 'masks/one_aorta.nii.gz', np.ones((3, 3, 3)))
    def fake_predict(ct, output, **kwargs):
        output.mkdir(parents=True)
        return ref, {'test_fixture': True}
    monkeypatch.setattr(cohort, 'predict', fake_predict)
    summary = cohort.evaluate(hospital, tmp_path / 'out')
    assert summary['succeeded'] == 1 and summary['failed'] == 1
    assert summary['paired_cases'] == 1
    assert summary['mean_delta_vs_vendor_reported'] == pytest.approx(.3)
    assert summary['paired_delta_patient_bootstrap_95ci'] is None


def test_api_auth_validation_and_mask_bundle(tmp_path, monkeypatch):
    from slicepoint_model import api
    monkeypatch.setenv('SLICEPOINT_API_TOKEN', 'test-token-at-least-32-characters-for-local-verification')
    client = TestClient(api.app)
    assert client.post('/v1/segment', files={'ct': ('a.nii.gz', b'bad')}).status_code == 401
    headers = {'Authorization': 'Bearer test-token-at-least-32-characters-for-local-verification'}
    assert client.post('/v1/segment', headers=headers, files={'ct': ('a.nii.gz', b'bad')}).status_code == 422
    image = save(tmp_path, 'ct.nii.gz', np.ones((3, 3, 3)))
    def fake_predict(ct, output, **kwargs):
        mask = save(output, 'aorta.nii.gz', np.ones((3, 3, 3)))
        return mask, {'test_fixture': True}
    monkeypatch.setattr(api, 'predict', fake_predict)
    response = client.post('/v1/segment', headers=headers, files={'ct': ('a.nii.gz', image.read_bytes())})
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        assert set(z.namelist()) == {'aorta.nii.gz', 'result.json'}
        assert json.loads(z.read('result.json'))['test_fixture']


def test_api_busy_and_size_limit(monkeypatch):
    from slicepoint_model import api
    monkeypatch.setenv('SLICEPOINT_API_TOKEN', 'test-token-at-least-32-characters-for-local-verification')
    client = TestClient(api.app)
    headers = {'Authorization': 'Bearer test-token-at-least-32-characters-for-local-verification'}
    api.lock.acquire()
    try:
        response = client.post('/v1/segment', headers=headers, files={'ct': ('a.nii.gz', b'x')})
        assert response.status_code == 503
    finally:
        api.lock.release()
    monkeypatch.setenv('MAX_UPLOAD_MB', '0')
    assert client.post('/v1/segment', headers=headers, files={'ct': ('a.nii.gz', b'x')}).status_code == 413


def test_downloader_handles_container_folder_prefix(tmp_path, monkeypatch):
    from slicepoint_model.download import download
    from azure.storage.blob import ContainerClient
    from types import SimpleNamespace
    captured = {}
    def zip_bytes(name):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as z:
            z.writestr(name, 'fixture')
        return stream.getvalue()
    class FakeContainer:
        def list_blobs(self, name_starts_with):
            captured['prefix'] = name_starts_with
            return [SimpleNamespace(name=name_starts_with + 'hospital_a.zip')]
        def download_blob(self, name, **kwargs):
            captured.setdefault('names', []).append(name)
            data = zip_bytes('practice/hospital_a/' + ('features.txt' if name.endswith('practice.zip') else 'images/case.txt'))
            return SimpleNamespace(readinto=lambda stream: stream.write(data))
    def from_url(url):
        captured['url'] = url
        return FakeContainer()
    monkeypatch.setattr(ContainerClient, 'from_container_url', from_url)
    monkeypatch.setenv('AZURE_DATA_SAS_URL', 'https://fixture.blob.core.windows.net/event/students?sig=fixture')
    download(tmp_path, hospital='hospital_a')
    assert captured['url'] == 'https://fixture.blob.core.windows.net/event?sig=fixture'
    assert captured['prefix'] == 'students/practice/images/'
    assert captured['names'] == ['students/practice/practice.zip', 'students/practice/images/hospital_a.zip']
    assert (tmp_path / 'practice/hospital_a/images/case.txt').exists()
    assert 'sig=' not in (tmp_path / 'download-manifest.json').read_text()
