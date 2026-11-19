"""Lädt die Windows-Programme COLMAP (ohne CUDA, läuft auf jedem PC) und OpenMVS
in den Ordner tools/ herunter. Wird vom Build automatisch aufgerufen.

    python tools/download_tools.py
    python tools/download_tools.py --colmap-url URL --openmvs-url URL   (feste Versionen)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UA = {"User-Agent": "ScanForge3D-build", "Accept": "application/vnd.github+json"}
if os.environ.get("GITHUB_TOKEN"):
    UA["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read()


def find_asset(repo: str, patterns: list[list[str]], exts=(".zip", ".7z")) -> str:
    rels = json.loads(get(f"https://api.github.com/repos/{repo}/releases?per_page=10"))
    for rel in rels:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        names = {a["name"]: a["browser_download_url"] for a in rel["assets"]}
        for pat in patterns:
            for n, url in names.items():
                low = n.lower()
                if low.endswith(exts) and all(p in low for p in pat):
                    print(f"  {repo} {rel['tag_name']}: {n}")
                    return url
    raise SystemExit(f"Kein passendes Windows-Paket in {repo} gefunden. Bitte manuell herunterladen "
                     f"und nach {ROOT} entpacken (siehe README).")


def extract(data: bytes, url: str, dest: Path):
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if url.lower().endswith(".7z"):
        import py7zr
        with py7zr.SevenZipFile(io.BytesIO(data)) as z:
            z.extractall(dest)
    else:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            z.extractall(dest)


def check(dest: Path, exe: str):
    hits = list(dest.rglob(exe))
    if not hits:
        raise SystemExit(f"{exe} wurde nach dem Entpacken nicht gefunden in {dest}")
    print(f"  OK: {hits[0].relative_to(ROOT)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--colmap-url")
    ap.add_argument("--openmvs-url")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    if a.force or not list((ROOT / "colmap").rglob("colmap.exe")):
        print("COLMAP …")
        url = a.colmap_url or find_asset("colmap/colmap", [["windows", "nocuda"], ["windows", "no-cuda"]])
        extract(get(url), url, ROOT / "colmap")
    check(ROOT / "colmap", "colmap.exe")

    if a.force or not list((ROOT / "openmvs").rglob("DensifyPointCloud.exe")):
        print("OpenMVS …")
        url = a.openmvs_url or find_asset("cdcseacave/openMVS", [["win", "x64"], ["windows"], ["win"]])
        extract(get(url), url, ROOT / "openmvs")
    check(ROOT / "openmvs", "DensifyPointCloud.exe")


if __name__ == "__main__":
    sys.exit(main())
