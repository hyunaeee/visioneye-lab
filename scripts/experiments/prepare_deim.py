"""Prepare pinned official DEIMv2 code/config/weights without running inference."""
from __future__ import annotations
import hashlib
import json
import subprocess
import urllib.request

from paths import HERE, RUNTIME

CODE_URL = 'https://github.com/Intellindust-AI-Lab/DEIMv2.git'
CODE_REVISION = '1d2ca42171570c713e78fc6a766ec5104b7f4724'


def main():
    base = RUNTIME / 'deim'
    repo = base / 'repo'
    base.mkdir(parents=True, exist_ok=True)
    if not repo.exists():
        subprocess.run(['git', '-c', 'http.sslBackend=openssl', 'clone', CODE_URL, str(repo)], check=True)
        subprocess.run(['git', '-C', str(repo), 'checkout', '--detach', CODE_REVISION], check=True)
    actual = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != CODE_REVISION:
        raise RuntimeError('Existing DEIM checkout differs from the pinned revision; it was not changed')
    manifest = json.loads((HERE / 'deim-assets.json').read_text(encoding='utf-8'))
    weights = base / 'weights'
    weights.mkdir(exist_ok=True)
    for name, record in manifest['files'].items():
        path = weights / name
        if not path.exists():
            partial = path.with_suffix(path.suffix + '.part')
            with urllib.request.urlopen(record['url'], timeout=120) as source, partial.open('wb') as output:
                while block := source.read(1024 * 1024):
                    output.write(block)
            partial.replace(path)
        if path.stat().st_size != record['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
            raise RuntimeError(f'Official DEIM artifact checksum differs: {name}')
    print('DEIMv2-S official code, paired config and checkpoint hashes verified; no inference run.')


if __name__ == '__main__':
    main()
