"""Explicit preparation of pinned public artifacts; never runs inference.

All downloaded artifacts and virtual environments stay in ignored .runtime.
An existing environment or unexpected checkout is preserved, not overwritten.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request
import venv

HERE = Path(__file__).resolve().parent
RUNTIME = HERE / '.runtime'
REVISION = '29320b6fd828f8e0987a71426cf2d961b09dfed7'
RT_REPOSITORY = 'https://github.com/lyuwenyu/RT-DETR.git'
RT_NAME = 'rtdetrv2_r18vd_120e_coco_rerun_48.1.pth'
ARTIFACTS = {
    'yolo26n': ('models/yolo26n.pt', 'https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt', '9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef', 5544453),
    'yolov8n': ('models/yolov8n.pt', 'https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8n.pt', 'f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36', 6549796),
    'yolo11n': ('models/yolo11n.pt', 'https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11n.pt', '0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1', 5613764),
    'rtdetrv2_s': ('rtdetr/weights/' + RT_NAME, 'https://github.com/lyuwenyu/storage/releases/download/v0.2/' + RT_NAME, '2ace52184b620204004509b72752ac7bfe64aadaf7fc1d076b18df8ab5a5c77e', 81198974),
}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def assets(selection):
    keys = ARTIFACTS if selection == 'all' else ['rtdetrv2_s'] if selection == 'rtdetr' else ['yolo26n', 'yolov8n', 'yolo11n']
    report = []
    for key in keys:
        relative, url, expected, size = ARTIFACTS[key]
        target = RUNTIME / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.stat().st_size != size or digest(target) != expected:
                raise RuntimeError(f'Existing {target.name} differs; preserved without replacement')
        else:
            partial = target.with_name(target.name + '.part')
            if partial.exists():
                raise FileExistsError(f'Partial download already exists: {partial}')
            request = urllib.request.Request(url, headers={'User-Agent': 'VisionEye-reproduction/1.0'})
            with urllib.request.urlopen(request, timeout=120) as response, partial.open('xb') as output:
                while block := response.read(1024 * 1024):
                    output.write(block)
            if partial.stat().st_size != size or digest(partial) != expected:
                raise RuntimeError(f'{partial.name} failed pinned size/SHA-256 validation')
            partial.replace(target)
        report.append({'model': key, 'file': relative, 'source_url': url, 'sha256': expected, 'bytes': size})
    print(json.dumps({'assets': report, 'inference_performed': False}, indent=2))


def checkout():
    repo = RUNTIME / 'rtdetr/repo'
    repo.parent.mkdir(parents=True, exist_ok=True)
    if repo.exists():
        actual = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
        dirty = subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain'], text=True).strip()
        if actual != REVISION or dirty:
            raise RuntimeError('Existing RT-DETR checkout differs or is modified; preserved without checkout/reset')
    else:
        subprocess.run(['git', 'clone', '--no-checkout', RT_REPOSITORY, str(repo)], check=True)
        subprocess.run(['git', '-C', str(repo), 'checkout', '--detach', REVISION], check=True)
    actual = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != REVISION:
        raise RuntimeError('RT-DETR checkout revision mismatch')
    print(json.dumps({'repository': RT_REPOSITORY, 'revision': actual, 'inference_performed': False}))


def environment():
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('Use Python 3.12; recorded measurement interpreter was 3.12.14')
    location = RUNTIME / 'env'
    if location.exists():
        raise FileExistsError('Existing .runtime/env preserved; create a fresh checkout to re-prepare')
    venv.EnvBuilder(with_pip=True).create(location)
    python = location / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    subprocess.run([str(python), '-m', 'pip', 'install', '--index-url', 'https://download.pytorch.org/whl/cu128', 'torch==2.11.0+cu128', 'torchvision==0.26.0+cu128'], check=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(HERE / 'requirements.txt')], check=True)
    subprocess.run([str(python), '-m', 'pip', 'check'], check=True)
    print(json.dumps({'environment': '.runtime/env', 'inference_performed': False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', choices=['yolo', 'rtdetr', 'all'], help='Download official weights and verify fixed SHA-256/size')
    parser.add_argument('--code', action='store_true', help='Clone exact official RT-DETR code revision')
    parser.add_argument('--environment', action='store_true', help='Create a fresh Python 3.12 CUDA 12.8 environment and install pinned main dependencies')
    args = parser.parse_args()
    if not any((args.assets, args.code, args.environment)):
        parser.print_help()
        return
    if args.environment:
        environment()
    if args.code:
        checkout()
    if args.assets:
        assets(args.assets)


if __name__ == '__main__':
    main()
