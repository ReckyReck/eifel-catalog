#!/usr/bin/env python3
"""Offline tests for scripts/build_catalog.py (no network). Run:  python3 tests/test_build_catalog.py"""
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://github.com/ReckyReck/eifel-catalog/releases/download"


def make_zip(bundles: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for b in bundles:
            z.writestr(f"{b}/Contents/Info.plist", "<plist/>")
    return buf.getvalue()


def release(tag, version, files, prerelease=False, body="- Faster meters\n- Fixed preset loading"):
    return {"tag_name": tag, "draft": False, "prerelease": prerelease, "published_at": "2026-11-24T10:00:00Z",
            "body": body,
            "assets": [{"name": n, "browser_download_url": f"{BASE}/{tag}/{n}"} for n in files]}


def run(folder: Path, releases: list, files: dict) -> tuple[int, dict | None, str]:
    (folder / "releases.json").write_text(json.dumps(releases))
    for name, data in files.items():
        (folder / name).write_bytes(data)
    out = folder / "_site"
    p = subprocess.run([sys.executable, "-I", str(ROOT / "scripts/build_catalog.py"), "--fixtures", str(folder),
                        "--out", str(out), "--now", "2026-11-24T10:00:00Z"], capture_output=True, text=True)
    cat = json.loads((out / "catalog.json").read_text()) if p.returncode == 0 else None
    return p.returncode, cat, p.stdout + p.stderr


MAC = make_zip(["Reckys Velvet.component", "Reckys Velvet.vst3"])
WIN = make_zip(["Reckys Velvet.vst3"])
GOOD = {"ReckysVelvet-1.0.0-macos.zip": MAC, "ReckysVelvet-1.0.0-windows.zip": WIN,
        "ReckysVelvet-1.1.0-macos.zip": MAC, "ReckysVelvet-1.1.0-windows.zip": WIN}

failures = 0


def check(name, cond, detail=""):
    global failures
    print(("  ok   " if cond else "  FAIL ") + name)
    if not cond:
        failures += 1
        print(detail)


with tempfile.TemporaryDirectory() as t:
    d = Path(t)
    # 1. newest stable release wins; prerelease and other plug-ins are ignored
    rels = [release("reckys-velvet-v1.0.0", "1.0.0", ["ReckysVelvet-1.0.0-macos.zip", "ReckysVelvet-1.0.0-windows.zip"]),
            release("reckys-velvet-v1.1.0", "1.1.0", ["ReckysVelvet-1.1.0-macos.zip", "ReckysVelvet-1.1.0-windows.zip"]),
            release("reckys-velvet-v2.0.0", "2.0.0", [], prerelease=True),
            release("reckys-rider-v9.0.0", "9.0.0", [])]
    code, cat, out = run(d, rels, GOOD)
    check("builds a valid catalog", code == 0, out)
    if cat:
        v = cat["plugins"][0]
        check("picks 1.1.0 (newest stable)", v["latest"]["version"] == "1.1.0", json.dumps(v, indent=1))
        mac = next(a for a in v["latest"]["assets"] if a["platform"] == "macos")
        check("SHA-256 and size come from the file",
              mac["sha256"] == hashlib.sha256(MAC).hexdigest() and mac["size"] == len(MAC))
        check("mac ZIP contains au + vst3", mac["contains"] == ["au", "vst3"])
        check("changelog from release text", v["latest"]["changelog"] == ["Faster meters", "Fixed preset loading"])
        check("schemaVersion 1", cat["schemaVersion"] == 1)

    # 2. a ZIP without the AU bundle is refused
    with tempfile.TemporaryDirectory() as t2:
        bad = dict(GOOD, **{"ReckysVelvet-1.0.0-macos.zip": make_zip(["Reckys Velvet.vst3"])})
        code, _, out = run(Path(t2), rels[:1], bad)
        check("refuses a ZIP with a missing bundle", code != 0 and "missing" in out, out)

    # 3. GitHub's own checksum must agree
    with tempfile.TemporaryDirectory() as t3:
        r = release("reckys-velvet-v1.0.0", "1.0.0", ["ReckysVelvet-1.0.0-macos.zip", "ReckysVelvet-1.0.0-windows.zip"])
        r["assets"][0]["digest"] = "sha256:" + "0" * 64
        code, _, out = run(Path(t3), [r], GOOD)
        check("refuses when GitHub's checksum differs", code != 0 and "checksum" in out, out)

    # 4. no release yet -> catalog is valid and empty
    with tempfile.TemporaryDirectory() as t4:
        code, cat, out = run(Path(t4), [], {})
        check("no release yet: empty but valid catalog", code == 0 and cat["plugins"] == [], out)

print("\nAll tests passed." if not failures else f"\n{failures} test(s) FAILED.")
sys.exit(1 if failures else 0)
