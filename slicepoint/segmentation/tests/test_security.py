from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from slicepoint_model.security import SecurityMiddleware

TOKEN = 'a-long-random-looking-test-token-more-than-32-characters'


@pytest.fixture
def secure_client(monkeypatch):
    monkeypatch.setenv('SLICEPOINT_API_TOKEN', TOKEN)
    app = FastAPI(docs_url=None, openapi_url=None)
    app.add_middleware(SecurityMiddleware)
    @app.post('/v1/segment')
    async def endpoint(request: Request):
        return {'bytes': len(await request.body())}
    return TestClient(app)


def test_auth_before_body_parsing_and_security_headers(secure_client):
    response = secure_client.post('/v1/segment', content=b'invalid multipart payload')
    assert response.status_code == 401
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert secure_client.get('/openapi.json').status_code == 404


def test_weak_secret_fails_closed(secure_client, monkeypatch):
    monkeypatch.setenv('SLICEPOINT_API_TOKEN', 'short')
    assert secure_client.post('/v1/segment', headers={'Authorization': 'Bearer short'}).status_code == 503


def test_declared_oversize_rejected_early(secure_client, monkeypatch):
    monkeypatch.setenv('MAX_UPLOAD_MB', '1')
    response = secure_client.post('/v1/segment', content=b'x', headers={
        'Authorization': f'Bearer {TOKEN}', 'Content-Length': str(3 * 1024 * 1024)})
    assert response.status_code == 413


def test_chunked_oversize_rejected(secure_client, monkeypatch):
    monkeypatch.setenv('MAX_UPLOAD_MB', '1')
    def chunks():
        for _ in range(3):
            yield b'x' * 1024 * 1024
    response = secure_client.post('/v1/segment', content=chunks(), headers={'Authorization': f'Bearer {TOKEN}'})
    assert response.status_code == 413


def test_authenticated_rate_limit(secure_client, monkeypatch):
    monkeypatch.setenv('MAX_REQUESTS_PER_MINUTE', '2')
    headers = {'Authorization': f'Bearer {TOKEN}'}
    assert secure_client.post('/v1/segment', headers=headers).status_code == 200
    assert secure_client.post('/v1/segment', headers=headers).status_code == 200
    response = secure_client.post('/v1/segment', headers=headers)
    assert response.status_code == 429 and response.headers['retry-after'] == '60'


def test_bad_auth_attempts_rate_limited(secure_client):
    for _ in range(10):
        assert secure_client.post('/v1/segment').status_code == 401
    assert secure_client.post('/v1/segment').status_code == 429
