#!/usr/bin/env python3
"""Install optional media dependencies in an isolated per-user environment."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from bili_core.common import home, private_dir


def main():
    uv = shutil.which('uv')
    target = home() / 'venv'
    requirements = Path(__file__).with_name('requirements.txt')
    if not uv:
        print(json.dumps({'ok': False, 'needs': ['安装 uv，或用 Python 3.10+ 创建 ' + str(target) + ' 并在该环境安装 scripts/requirements.txt。']}, ensure_ascii=False))
        return 2
    private_dir(home())
    if not target.exists():
        subprocess.run([uv, 'venv', '--python', '3.11', str(target)], check=True)
    py = target / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    subprocess.run([uv, 'pip', 'install', '--python', str(py), '-r', str(requirements)], check=True)
    print(json.dumps({'ok': True, 'python': str(py), 'model_download': 'Whisper 模型首次转写时下载；可用 HF_ENDPOINT 显式选择镜像。'}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
