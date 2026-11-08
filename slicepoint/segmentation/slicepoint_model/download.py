"""Only fetch the provided event container; never discover or guess private URLs."""
import json
import os
import zipfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def safe_extract(archive, destination):
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            target = (destination / entry.filename).resolve()
            if not target.is_relative_to(destination) or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unsafe archive path')
        z.extractall(destination)


def download(destination, release='practice', hospital=None, tables_only=False):
    from azure.storage.blob import ContainerClient
    url = os.environ.get('AZURE_DATA_SAS_URL')
    if not url:
        raise ValueError('Set AZURE_DATA_SAS_URL to the read-only kickoff container URL')
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or not parts.hostname.endswith('.blob.core.windows.net'):
        raise ValueError('Expected an HTTPS Azure Blob container URL')
    # Event links can point at a prefix inside a container, e.g. /container/students.
    path = parts.path.strip('/').split('/', 1)
    prefix = path[1].rstrip('/') + '/' if len(path) == 2 else ''
    container_url = urlunsplit((parts.scheme, parts.netloc, '/' + path[0], parts.query, ''))
    client = ContainerClient.from_container_url(container_url)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    selected = [prefix + f'{release}/{release}.zip']
    if not tables_only:
        blobs = client.list_blobs(name_starts_with=prefix + f'{release}/images/')
        selected += [b.name for b in blobs if b.name.endswith('.zip') and
                     (hospital is None or Path(b.name).stem == hospital)]
        if len(selected) == 1:
            raise ValueError('No matching image archives are available')
    records = []
    from .core import sha256
    for name in selected:
        relative = Path(name.removeprefix(prefix))
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe blob path')
        archive = destination / '_archives' / relative
        archive.parent.mkdir(parents=True, exist_ok=True)
        temporary = archive.with_suffix('.partial')
        try:
            with open(temporary, 'wb') as stream:
                client.download_blob(name, max_concurrency=8).readinto(stream)
            temporary.replace(archive)
            safe_extract(archive, destination)
        finally:
            temporary.unlink(missing_ok=True)
        records.append({'blob': name, 'sha256': sha256(archive), 'bytes': archive.stat().st_size})
        print(f'Downloaded {relative} ({archive.stat().st_size:,} bytes)')
    (destination / 'download-manifest.json').write_text(json.dumps(records, indent=2))
