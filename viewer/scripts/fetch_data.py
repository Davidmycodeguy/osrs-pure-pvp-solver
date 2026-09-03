"""Download the viewer datasets from a GitHub release into viewer/public/data.

The ranked builds and KO kits are too large for git, so each dataset snapshot is published as
gzipped assets on a GitHub release.  This script lists the release, downloads every ``*.json.gz``
asset that is missing or stale, and inflates it next to the archive (the viewer reads the plain
JSON).  It needs only the standard library.

Usage:
    python scripts/fetch_data.py                 # the default snapshot, both combat levels
    python scripts/fetch_data.py --level 40      # only the level-40 datasets
    python scripts/fetch_data.py --tag data-2026-09-02
    python scripts/fetch_data.py --force         # re-download even if the files exist

Set ``GITHUB_TOKEN`` (or ``GH_TOKEN``) to download from a private repository or to avoid the
unauthenticated API rate limit.  To regenerate the datasets yourself instead, run the pipeline
(``pure_math/scripts/run_pipeline.sh`` or ``run_pipeline.ps1``) and ``scripts/export_build_data.py``.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPOSITORY = "Davidmycodeguy/osrs-pure-pvp-solver"
DEFAULT_TAG = "data-2026-09-02"
API_ROOT = "https://api.github.com"
DATA_DIR = Path(__file__).resolve().parents[1] / "public" / "data"
USER_AGENT = "purelab-fetch-data/1.0 (+https://github.com/Davidmycodeguy/osrs-pure-pvp-solver)"
CHUNK_BYTES = 1 << 20


@dataclass(frozen=True)
class Asset:
    """One downloadable file attached to the release."""

    name: str
    url: str
    size: int

    @property
    def combat_level(self) -> int | None:
        stem = self.name.removesuffix(".json.gz")
        _, _, level = stem.rpartition("-")
        return int(level) if level.isdigit() else None


def _headers(accept: str) -> dict[str, str]:
    headers = {"Accept": accept, "User-Agent": USER_AGENT, "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _request(url: str, accept: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers=_headers(accept))


def list_assets(repository: str, tag: str) -> tuple[Asset, ...]:
    """Return the ``*.json.gz`` assets attached to the release for ``tag``."""
    url = f"{API_ROOT}/repos/{repository}/releases/tags/{tag}"
    try:
        with urllib.request.urlopen(_request(url, "application/vnd.github+json"), timeout=60) as response:
            release = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise SystemExit(
                f"No release tagged {tag!r} on {repository}. If the repository is private, set GITHUB_TOKEN."
            ) from error
        raise SystemExit(f"GitHub API returned {error.code} for {url}") from error
    except OSError as error:
        raise SystemExit(f"Could not reach GitHub: {error}") from error
    assets = tuple(
        Asset(name=str(item["name"]), url=str(item["url"]), size=int(item["size"]))
        for item in release.get("assets", [])
        if str(item.get("name", "")).endswith(".json.gz")
    )
    if not assets:
        raise SystemExit(f"Release {tag!r} has no *.json.gz assets")
    return assets


def _is_current(asset: Asset, destination: Path) -> bool:
    return destination.exists() and destination.stat().st_size == asset.size


def download(asset: Asset, destination: Path) -> None:
    """Stream one asset to ``destination`` via a temporary file."""
    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        with (
            urllib.request.urlopen(_request(asset.url, "application/octet-stream"), timeout=300) as response,
            partial.open("wb") as handle,
        ):
            received = 0
            while chunk := response.read(CHUNK_BYTES):
                handle.write(chunk)
                received += len(chunk)
                print(f"\r  {asset.name}: {received / 1_048_576:6.1f} / {asset.size / 1_048_576:.1f} MB", end="")
            print()
    except (OSError, urllib.error.HTTPError) as error:
        partial.unlink(missing_ok=True)
        raise SystemExit(f"Download of {asset.name} failed: {error}") from error
    if partial.stat().st_size != asset.size:
        partial.unlink(missing_ok=True)
        raise SystemExit(f"{asset.name}: expected {asset.size} bytes, received {partial.stat().st_size}")
    partial.replace(destination)


def inflate(archive: Path) -> Path:
    """Write the plain JSON next to the ``.gz``; the viewer reads the JSON."""
    target = archive.with_suffix("")
    with gzip.open(archive, "rb") as source, target.open("wb") as sink:
        shutil.copyfileobj(source, sink, CHUNK_BYTES)
    return target


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tag", default=DEFAULT_TAG, help=f"release tag to fetch (default: {DEFAULT_TAG})")
    parser.add_argument("--repository", default=REPOSITORY, help=f"owner/name on GitHub (default: {REPOSITORY})")
    parser.add_argument("--level", type=int, action="append", help="combat level to fetch; repeatable (default: all)")
    parser.add_argument("--force", action="store_true", help="download even when the file already exists")
    parser.add_argument("--no-inflate", action="store_true", help="keep only the .gz files")
    parser.add_argument("--dest", type=Path, default=DATA_DIR, help=f"output directory (default: {DATA_DIR})")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    assets = list_assets(args.repository, args.tag)
    wanted = [asset for asset in assets if not args.level or asset.combat_level in args.level]
    if not wanted:
        levels = sorted({asset.combat_level for asset in assets if asset.combat_level is not None})
        raise SystemExit(f"Release {args.tag!r} has no datasets for level(s) {args.level}; available: {levels}")
    args.dest.mkdir(parents=True, exist_ok=True)
    print(f"Release {args.tag} on {args.repository}: {len(wanted)} file(s) -> {args.dest}")
    for asset in wanted:
        destination = args.dest / asset.name
        if not args.force and _is_current(asset, destination):
            print(f"  {asset.name}: up to date")
        else:
            download(asset, destination)
        if not args.no_inflate:
            inflated = inflate(destination)
            print(f"  {inflated.name}: {inflated.stat().st_size / 1_048_576:.1f} MB inflated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
