"""Download and verify the measured official RF-DETR Small checkpoint."""
import hashlib
import urllib.request

from paths import RUNTIME

URL = 'https://storage.googleapis.com/rfdetr/small_coco/checkpoint_best_regular.pth'
EXPECTED_SHA256 = 'd81979a9213a2109345158ce9232668df4c1ae52e9b8db3f2ec0a8cbad959b33'
EXPECTED_BYTES = 386045550


def main():
    target = RUNTIME / 'rfdetr-models' / 'rf-detr-small.pth'
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        partial = target.with_suffix('.pth.part')
        with urllib.request.urlopen(URL, timeout=120) as source, partial.open('wb') as output:
            while block := source.read(1024 * 1024):
                output.write(block)
        partial.replace(target)
    if target.stat().st_size != EXPECTED_BYTES or hashlib.sha256(target.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise RuntimeError('Official RF-DETR Small checkpoint differs from the measured artifact')
    print('RF-DETR Small checkpoint SHA-256 verified; no inference run.')


if __name__ == '__main__':
    main()
