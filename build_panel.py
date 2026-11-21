"""生成涂鸦面板源码归档和可独立打开的预览。"""

import base64
import zipfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parent
PANEL = ROOT / "tuya-panel"
PREVIEW = ROOT / "panel-preview"
OUTPUT = ROOT / "output" / "LB_PANEL_UI"
REQUIRED = (
    "project.tuya.json",
    "README.md",
    "miniprogram/app.js",
    "miniprogram/app.json",
    "miniprogram/pages/home/index.json",
    "miniprogram/pages/home/index.js",
    "miniprogram/pages/home/index.tyml",
    "miniprogram/pages/home/index.tyss",
)
ASSETS = {"cat-and-tray.png": (420, 290), "litter-scoop.png": (156, 156)}


def main():
    missing = [name for name in REQUIRED if not (PANEL / name).is_file()]
    if missing:
        raise SystemExit("面板工程文件缺失 " + ", ".join(missing))

    html = (PREVIEW / "index.html").read_text(encoding="utf-8")
    asset_paths = []
    for name, size in ASSETS.items():
        destination = PANEL / "miniprogram" / "assets" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(PREVIEW / name) as source:
            illustration = source.convert("RGBA")
            illustration.thumbnail(size, Image.Resampling.LANCZOS)
            illustration.save(destination, optimize=True)
        encoded = base64.b64encode(destination.read_bytes()).decode("ascii")
        html = html.replace(f'src="{name}"', f'src="data:image/png;base64,{encoded}"')
        asset_paths.append(destination)

    OUTPUT.mkdir(parents=True, exist_ok=True)
    preview_path = OUTPUT / "litterbox-panel-preview.html"
    preview_path.write_text(html, encoding="utf-8")

    zip_path = OUTPUT / "litterbox-panel-source.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in [*(PANEL / name for name in REQUIRED), *asset_paths]:
            archive.write(path, Path("tuya-panel") / path.relative_to(PANEL))

    print(preview_path)
    print(f"{zip_path} ({zip_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
