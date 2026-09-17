"""Create a new upload folder from a public-file allowlist (no Git or venv).

Usage: python tools/package_release.py D:/MOSAIC-upload-v0.2.0
Existing destinations are never replaced.
"""

import argparse
import hashlib
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from mosaic import __version__


def public_files():
    names = ['.gitignore', '.gitattributes', 'README.md', 'CHANGELOG.md',
             'CONTRIBUTING.md', 'pyproject.toml', 'requirements.txt',
             'run_app.bat', 'run_app.command']
    files = [ROOT / name for name in names]
    for folder in ('src', 'tests', 'tools', 'docs', '.github'):
        for path in (ROOT / folder).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix in ('.py', '.md', '.html', '.yml'):
                files.append(path)
    return sorted(files)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    destination = args.destination.resolve()
    archive = destination.with_suffix('.zip')
    if destination.exists() or archive.exists():
        raise SystemExit('Choose a new destination: existing folder/archive will not be overwritten.')
    destination.mkdir(parents=True)
    hashes = []
    for path in public_files():
        relative = path.relative_to(ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        if target.name == 'run_app.command':
            target.chmod(0o755)
        hashes.append(f'{hashlib.sha256(target.read_bytes()).hexdigest()}  {relative.as_posix()}')
    (destination / 'SHA256SUMS.txt').write_text('\n'.join(hashes) + '\n', encoding='utf-8')
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
        for path in sorted(destination.rglob('*')):
            if path.is_file():
                name = f'MOSAIC-{__version__}/{path.relative_to(destination).as_posix()}'
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = ((0o100755 if path.name == 'run_app.command' else 0o100644) << 16)
                output.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    print(f'Upload folder: {destination}')
    print(f'Source archive: {archive}')
    print(f'Public files: {len(hashes)}; SHA256 manifest included')


if __name__ == '__main__':
    main()
