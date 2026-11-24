# eifel-catalog

The public plug-in catalog for **Eifel Mastering Central**. This repository holds three things:

1. **`plugins/<id>/plugin.json`** – one small description per plug-in (written once, by hand).
2. **Releases** – the finished plug-in ZIPs that Central downloads. The plug-in repos stay private; their release
   workflow puts only the ZIPs here, with a tag `<id>-vX.Y.Z` (e.g. `reckys-velvet-v1.0.0`).
3. **`catalog.json`** on GitHub Pages – built automatically from 1 + 2:
   <https://reckyreck.github.io/eifel-catalog/catalog.json>. Never edit it by hand.

## How a release flows

```
plug-in repo (private): git tag v1.0.0
   └─ GitHub Actions builds Mac + Windows, zips the bundles
      └─ creates release "reckys-velvet-v1.0.0" HERE with the two ZIPs, then signals "plugin-released"
         └─ workflow "Build catalog" downloads the ZIPs, checks the bundles are inside,
            computes SHA-256 + size, validates, publishes catalog.json
            └─ Central shows "UPDATE READY"
```

## Files

| Path | What it is |
| --- | --- |
| `plugins/<id>/plugin.json` | Name, tagline, category, formats, bundle file names, bundle ID, minimum OS |
| `plugins/<id>/faceplate.png` | Screenshot of the plug-in's front panel, 2.5 : 1, title top left (shown at 260 × 104) |
| `schema/plugin.schema.json` | Rules for `plugin.json` |
| `schema/catalog.schema.json` | Rules for the generated `catalog.json` (schemaVersion 1) |
| `scripts/build_catalog.py` | Builds `catalog.json` |
| `tests/test_build_catalog.py` | Offline tests of the builder (run on every build) |
| `examples/catalog.example.json` | A sample catalog with fake checksums, for developing the app |
| `.github/workflows/build-catalog.yml` | Builds and publishes; runs on "plugin-released", on changes in `plugins/`, nightly, or by hand |

## Rules

- Versions are SemVer `X.Y.Z`. Release ZIPs are named `<Name>-<version>-macos.zip` / `-windows.zip`, with the
  bundles at the top level of the ZIP.
- `bundleNames` must match the real files exactly (the shared builds are called `Reckys <Name>`, without apostrophe).
- The release text becomes the changelog in Central: write 2–3 lines starting with `- `.
- A plug-in without a release yet is simply left out of the catalog.
- A release with a missing bundle, a damaged ZIP or a checksum that differs from GitHub's stops the build; the
  previous `catalog.json` stays online.

## Adding a new plug-in

1. `plugins/<id>/plugin.json` (copy `reckys-velvet` and adapt).
2. `plugins/<id>/faceplate.png`.
3. In the plug-in repo: the release workflow for Central (ZIP release + signal).
4. Tag the first release and check that `catalog.json` lists the plug-in.

## Test locally (optional)

```
cd ~/eifel-catalog && python3 tests/test_build_catalog.py
```
(needs `jsonschema`: `python3 -m pip install --user jsonschema`)
