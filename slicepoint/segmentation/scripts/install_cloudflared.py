"""Install Cloudflare's official tunnel binary locally and verify its release digest."""
import hashlib
import json
from pathlib import Path
import requests

root = Path(__file__).resolve().parents[1]
bin_dir = root / '.local/bin'
bin_dir.mkdir(parents=True, exist_ok=True)
release = requests.get('https://api.github.com/repos/cloudflare/cloudflared/releases/latest', timeout=30)
release.raise_for_status()
release = release.json()
asset = next(a for a in release['assets'] if a['name'] == 'cloudflared-linux-amd64')
expected = asset.get('digest', '')
if not expected.startswith('sha256:'):
    raise RuntimeError('Release has no SHA-256 digest; verify manually before installation')
destination = bin_dir / 'cloudflared'
part = destination.with_suffix('.partial')
with requests.get(asset['browser_download_url'], stream=True, timeout=60) as response:
    response.raise_for_status()
    digest = hashlib.sha256()
    with part.open('wb') as stream:
        for chunk in response.iter_content(1024 * 1024):
            stream.write(chunk)
            digest.update(chunk)
if digest.hexdigest() != expected.split(':', 1)[1]:
    part.unlink(missing_ok=True)
    raise RuntimeError('Official release checksum mismatch')
part.chmod(0o700)
part.replace(destination)
(bin_dir / 'cloudflared-release.json').write_text(json.dumps({
    'version': release['tag_name'], 'source': asset['browser_download_url'],
    'sha256': digest.hexdigest()}, indent=2))
print(f'Installed official cloudflared {release["tag_name"]}; SHA-256 matched the release metadata.')
