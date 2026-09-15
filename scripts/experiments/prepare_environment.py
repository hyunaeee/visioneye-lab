"""Create pinned experiment environments without changing an existing environment."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import subprocess
import sys
import venv

from paths import HERE, RUNTIME


def python_in(directory):
    return directory / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def run(executable, *arguments, env=None):
    subprocess.run([str(executable), '-B', *map(str, arguments)], check=True, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('environment', choices=['base', 'rfdetr', 'deim', 'reid'])
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('Use Python 3.12; the measured patch version was 3.12.14')
    base = RUNTIME / 'base-env'
    base_python = python_in(base)
    name = args.environment
    target = RUNTIME / ('reid-packages' if name == 'reid' else f'{name}-env')
    if target.exists():
        raise FileExistsError(f'{target.name} already exists; this script never replaces an environment')
    if name != 'base' and not base_python.is_file():
        raise RuntimeError('Prepare the base environment first')
    RUNTIME.mkdir(parents=True, exist_ok=True)
    lock = HERE / f'requirements-{name}-lock.txt'
    if name == 'reid':
        run(base_python, '-m', 'pip', 'install', '--no-deps', '--target', target, '-r', lock)
        env = dict(os.environ)
        env['PYTHONPATH'] = str(target)
        run(base_python, '-m', 'pip', 'check', env=env)
        return
    venv.EnvBuilder(with_pip=True).create(target)
    executable = python_in(target)
    run(executable, '-m', 'pip', 'install', '--no-deps', 'pip==25.0.1')
    if name == 'base':
        run(executable, '-m', 'pip', 'install', '--no-deps',
            'torch==2.11.0+cu128', 'torchvision==0.26.0+cu128',
            '--index-url', 'https://download.pytorch.org/whl/cu128')
    else:
        base_packages = subprocess.check_output([str(base_python), '-B', '-c',
            "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip()
        packages = subprocess.check_output([str(executable), '-B', '-c',
            "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True).strip()
        (Path(packages) / 'visioneye_shared.pth').write_text(base_packages + '\n', encoding='utf-8')
    run(executable, '-m', 'pip', 'install', '--no-deps', '-r', lock)
    run(executable, '-m', 'pip', 'check')
    print(f'Prepared {name}; package versions are pinned and the base environment was not upgraded.')


if __name__ == '__main__':
    main()
