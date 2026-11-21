"""只准备本项目工具目录，不操作目标硬件。"""
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"
TOOLS.mkdir(exist_ok=True)
(ROOT / "build").mkdir(exist_ok=True)
env = TOOLS / "serial-venv"
if not (env / "Scripts/python.exe").exists():
    subprocess.run([sys.executable, "-m", "venv", str(env)], check=True)
python = env / "Scripts/python.exe"
subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                "stcgal==1.10", "pyserial==3.5", "tqdm==4.67.1", "colorama==0.4.6"], check=True)
installer = TOOLS / "c251v560.exe"
if not installer.exists():
    url = "https://www.keil.com/files/eval/c251v560.exe"
    print("Downloading official C251 evaluation installer:", url, flush=True)
    with urllib.request.urlopen(url, timeout=45) as response:
        with installer.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
    if installer.read_bytes()[:2] != b"MZ":
        raise RuntimeError("下载结果不是Windows安装程序，请检查官方下载服务。")
destination = TOOLS / 'keil-c251'
with zipfile.ZipFile(installer) as archive:
    for name in archive.namelist():
        if name.startswith('C251/') or 'license' in name.lower():
            output = (destination / name).resolve()
            if destination.resolve() not in output.parents:
                raise RuntimeError('安装包包含越界路径')
            # 只在首次准备时解包，不覆盖已有工具修改。
            if not output.exists():
                archive.extract(name, destination)
receipt = {'c251_source': 'https://www.keil.com/files/eval/c251v560.exe',
           'c251_sha256': hashlib.sha256(installer.read_bytes()).hexdigest(),
           'license': 'official evaluation, 2KB object-code limit',
           'serial_packages': ['stcgal==1.10','pyserial==3.5','tqdm==4.67.1','colorama==0.4.6']}
(TOOLS / 'setup-receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
print('Serial tools and isolated C251 evaluation tools prepared:', destination)
