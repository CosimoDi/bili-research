#!/usr/bin/env python3
"""Build a portable zip and optionally install without overwriting other skills."""
import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'skills' / 'bili-research'


def files(root):
    return sorted(p for p in root.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')


def digest(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files(root)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--install-to', type=Path)
    a = ap.parse_args()
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    archive = dist / 'bili-research.zip'
    manifest = digest(SOURCE)
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in files(SOURCE):
            z.write(p, 'bili-research/' + str(p.relative_to(SOURCE)))
    (dist / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    if a.install_to:
        destination = a.install_to.expanduser().resolve()
        if destination.exists():
            if digest(destination) != manifest:
                raise SystemExit('目标目录已有不同内容；请先人工检查，安装器不会覆盖。')
        else:
            shutil.copytree(SOURCE, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        if digest(destination) != manifest:
            raise SystemExit('安装内容校验不一致。')
    print(json.dumps({'archive': str(archive), 'files': len(manifest),
                      'installed': str(a.install_to) if a.install_to else None, 'hashes_verified': bool(a.install_to)}, ensure_ascii=False))


if __name__ == '__main__': main()
