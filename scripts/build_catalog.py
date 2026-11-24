#!/usr/bin/env python3
"""Builds catalog.json for Eifel Mastering Central.

Runs on GitHub Actions (workflow "Build catalog"). For every plugins/<id>/plugin.json it finds the newest release
in this repository whose tag is "<id>-vX.Y.Z", downloads its ZIPs, checks that the bundles named in plugin.json are
inside, and writes version, download URL, SHA-256, size and changelog into catalog.json. The result is validated
against schema/catalog.schema.json and copied, with the faceplate pictures, into the site folder for GitHub Pages.

  python3 scripts/build_catalog.py --out _site                        (online: reads the GitHub releases)
  python3 scripts/build_catalog.py --out _site --fixtures tests/fixtures  (offline test with fake releases)
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "ReckyReck/eifel-catalog"
PAGES_URL = "https://reckyreck.github.io/eifel-catalog"
SCHEMA_VERSION = 1
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
ASSET_NAME = re.compile(r"-(?P<version>\d+\.\d+\.\d+)-(?P<platform>macos|windows)\.zip$")
ARCH = {"macos": "universal", "windows": "x64"}
BUNDLE_SUFFIX = {"au": ".component", "vst3": ".vst3", "clap": ".clap"}


class CatalogError(Exception):
    pass


def log(msg: str) -> None:
    print(msg, flush=True)


# ---- sources: GitHub (online) or a fixtures folder (offline test) ---------------------------------------------------
class GitHubSource:
    def __init__(self, repo: str, token: str | None):
        self.repo, self.token = repo, token

    def _get(self, url: str, accept: str = "application/vnd.github+json") -> bytes:
        req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "eifel-catalog-builder"})
        if self.token and url.startswith("https://api.github.com/"):
            req.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()

    def releases(self) -> list[dict]:
        out, page = [], 1
        while True:
            batch = json.loads(self._get(f"https://api.github.com/repos/{self.repo}/releases?per_page=100&page={page}"))
            out += batch
            if len(batch) < 100:
                return out
            page += 1

    def download(self, asset: dict) -> bytes:
        return self._get(asset["browser_download_url"], accept="application/octet-stream")


class FixtureSource:
    """tests/fixtures/releases.json (GitHub API format) + the ZIPs next to it."""

    def __init__(self, folder: Path):
        self.folder = folder

    def releases(self) -> list[dict]:
        return json.loads((self.folder / "releases.json").read_text("utf-8"))

    def download(self, asset: dict) -> bytes:
        return (self.folder / asset["name"]).read_bytes()


# ---- helpers ---------------------------------------------------------------------------------------------------------
def semver_key(v: str) -> tuple[int, int, int]:
    a, b, c = v.split(".")
    return int(a), int(b), int(c)


def changelog_from(body: str | None) -> list[str]:
    lines = [l.strip() for l in (body or "").splitlines() if l.strip()]
    bullets = [re.sub(r"^[-*•]\s*", "", l) for l in lines if re.match(r"^[-*•]\s+", l)]
    items = bullets or [l for l in lines if not l.startswith("#")]
    return items[:12]


def bundles_in_zip(data: bytes) -> set[str]:
    """Top-level bundle folder names (*.component / *.vst3 / *.clap) inside a ZIP."""
    names = set()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        bad = z.testzip()
        if bad:
            raise CatalogError(f"damaged file inside the ZIP: {bad}")
        for n in z.namelist():
            if n.startswith("/") or ".." in n.split("/") or n.startswith("__MACOSX/"):
                if not n.startswith("__MACOSX/"):
                    raise CatalogError(f"unsafe path inside the ZIP: {n}")
                continue
            top = n.split("/")[0]
            if top.endswith(tuple(BUNDLE_SUFFIX.values())):
                names.add(top)
    return names


def load_plugins() -> list[dict]:
    from jsonschema import Draft202012Validator

    schema = json.loads((ROOT / "schema/plugin.schema.json").read_text("utf-8"))
    validator = Draft202012Validator(schema)
    plugins = []
    for f in sorted((ROOT / "plugins").glob("*/plugin.json")):
        p = json.loads(f.read_text("utf-8"))
        errors = sorted(validator.iter_errors(p), key=lambda e: list(e.path))
        if errors:
            raise CatalogError(f"{f.relative_to(ROOT)}: " + "; ".join(f"{list(e.path)}: {e.message}" for e in errors))
        if p["id"] != f.parent.name:
            raise CatalogError(f"{f.relative_to(ROOT)}: id '{p['id']}' must equal its folder name '{f.parent.name}'")
        for plat, fmts in p["formats"].items():
            for fmt in fmts:
                if fmt not in p["bundleNames"]:
                    raise CatalogError(f"{f.relative_to(ROOT)}: format '{fmt}' ({plat}) has no entry in bundleNames")
        plugins.append(p)
    return plugins


def build_entry(p: dict, releases: list[dict], source) -> dict | None:
    pid = p["id"]
    channel = p.get("channel", "stable")
    tag_re = re.compile(rf"^{re.escape(pid)}-v(\d+\.\d+\.\d+)$")
    candidates = []
    for r in releases:
        m = tag_re.match(r.get("tag_name", ""))
        if not m or r.get("draft"):
            continue
        if r.get("prerelease") and channel == "stable":
            continue
        candidates.append((semver_key(m.group(1)), m.group(1), r))
    if not candidates:
        log(f"  {pid}: no release yet (tag '{pid}-vX.Y.Z') - left out of the catalog for now")
        return None
    _, version, rel = max(candidates, key=lambda c: c[0])
    log(f"  {pid}: newest release {version}")

    assets = []
    for plat, fmts in p["formats"].items():
        matches = [a for a in rel.get("assets", [])
                   if (m := ASSET_NAME.search(a["name"])) and m["platform"] == plat and m["version"] == version]
        if len(matches) != 1:
            raise CatalogError(f"{pid} {version}: expected exactly one '*-{version}-{plat}.zip' in the release, "
                               f"found {len(matches)}")
        a = matches[0]
        data = source.download(a)
        inside = bundles_in_zip(data)
        contains = []
        for fmt in fmts:
            want = p["bundleNames"][fmt]
            if want not in inside:
                raise CatalogError(f"{pid} {version}: '{want}' is missing in {a['name']} (found: {sorted(inside) or 'nothing'})")
            contains.append(fmt)
        sha = hashlib.sha256(data).hexdigest()
        digest = a.get("digest")  # GitHub's own checksum, when it provides one
        if digest and digest.startswith("sha256:") and digest[7:] != sha:
            raise CatalogError(f"{pid} {version}: {a['name']} checksum differs from GitHub's - download damaged?")
        assets.append({"platform": plat, "arch": ARCH[plat], "url": a["browser_download_url"],
                       "sha256": sha, "size": len(data), "contains": contains})
        log(f"    {plat}: {a['name']}  {len(data):,} bytes  sha256 {sha[:12]}...")

    image = None
    if p.get("image") and (ROOT / p["image"]).is_file():
        image = f"{PAGES_URL}/{p['image']}"
    elif p.get("image"):
        log(f"    note: {p['image']} not found - Central shows a blank faceplate until it is added")

    entry = {k: p[k] for k in ("id", "name", "tagline", "category")}
    entry.update({
        "image": image,
        "channel": channel,
        "formats": p["formats"],
        "bundleNames": p["bundleNames"],
    })
    if "bundleId" in p:
        entry["bundleId"] = p["bundleId"]
    entry["latest"] = {
        "version": version,
        "releasedAt": (rel.get("published_at") or rel.get("created_at") or "")[:10],
        "changelog": changelog_from(rel.get("body")),
        "minOS": p.get("minOS", {}),
        "assets": assets,
    }
    return entry


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_site", help="site folder for GitHub Pages")
    ap.add_argument("--fixtures", help="offline test: folder with releases.json and ZIPs")
    ap.add_argument("--now", help="fixed generatedAt (for tests)")
    args = ap.parse_args()

    from jsonschema import Draft202012Validator, FormatChecker

    source = FixtureSource(Path(args.fixtures)) if args.fixtures else GitHubSource(REPO, os.environ.get("GITHUB_TOKEN"))
    try:
        plugins = load_plugins()
        log(f"{len(plugins)} plug-in(s) in plugins/")
        releases = source.releases()
        entries = [e for p in plugins if (e := build_entry(p, releases, source))]
    except CatalogError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1

    now = args.now or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    catalog = {"schemaVersion": SCHEMA_VERSION, "generatedAt": now, "plugins": entries}

    schema = json.loads((ROOT / "schema/catalog.schema.json").read_text("utf-8"))
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(catalog))
    if args.fixtures:  # fixture URLs need not point at the real repository
        errors = [e for e in errors if not (e.validator == "pattern" and list(e.path)[-1:] == ["url"])]
    if errors:
        for e in errors:
            print(f"ERROR: catalog.json {list(e.path)}: {e.message}", file=sys.stderr)
        return 1

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "catalog.json").write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", "utf-8")
    for p in plugins:
        if p.get("image") and (ROOT / p["image"]).is_file():
            dest = out / p["image"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / p["image"], dest)
    shutil.copytree(ROOT / "schema", out / "schema")
    index = ROOT / "site" / "index.html"
    if index.is_file():
        shutil.copy2(index, out / "index.html")
    (out / ".nojekyll").write_text("")
    log(f"\nDone: {out / 'catalog.json'} with {len(entries)} plug-in(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
