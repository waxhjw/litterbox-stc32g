"""Cache the STC IDE compiler worker locally. No project sources are sent."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.request import urlopen


BASE = "https://stcide.stcaimcu.com/"
ROOT = Path(__file__).resolve().parents[1] / ".tools" / "stc-ide"
CHUNK = re.compile(rb'["\']\./(?:chunks/)?(chunk-[A-Z0-9]+\.js)["\']')


def download(name):
    with urlopen(BASE + name, timeout=25) as stream:
        body = stream.read()
    path = ROOT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return {
        "name": name,
        "sha256": sha256(body).hexdigest(),
        "imports": {"chunks/" + m.decode() for m in CHUNK.findall(body)},
    }


def main():
    prior = ROOT / "manifest.json"
    if prior.exists():
        raise SystemExit("STC IDE cache already exists. Keep the pinned compiler for reproducible builds.")
    seen = set()
    pending = {"ide.worker.js"}
    hashes = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        while pending:
            seen.update(pending)
            found = set()
            for item in pool.map(download, sorted(pending)):
                hashes[item["name"]] = item["sha256"]
                found.update(item["imports"])
            pending = found - seen
    (ROOT / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    prior.write_text(json.dumps({"source": BASE, "files": hashes}, indent=2)+"\n", encoding="utf-8")
    print("STC IDE:", len(hashes), "assets", ROOT)


if __name__ == "__main__":
    main()
