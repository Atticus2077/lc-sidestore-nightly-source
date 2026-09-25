#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import io
import json
import os
import plistlib
import re
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

UPSTREAM = "LiveContainer/LiveContainer"
TAG = "nightly"
ASSET_NAME = "LiveContainer+SideStore.ipa"
EXPECTED_BUNDLE_ID = "com.kdt.livecontainer"
REPO = os.environ.get("GITHUB_REPOSITORY", "Atticus2077/lc-sidestore-nightly-source")
ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "source.json"
STATE_PATH = ROOT / "state.json"
OUT_DIR = ROOT / "dist"
OUT_IPA = OUT_DIR / ASSET_NAME
KEEP_VERSIONS = 8


def gh_json(url: str):
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "lc-sidestore-nightly-source",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "lc-sidestore-nightly-source"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def find_upstream_commit(release: dict) -> str:
    body = release.get("body") or ""
    m = re.search(r"/commit/([0-9a-fA-F]{40})", body)
    if m:
        return m.group(1).lower()
    target = str(release.get("target_commitish") or "")
    if re.fullmatch(r"[0-9a-fA-F]{40}", target):
        return target.lower()
    ref = gh_json(f"https://api.github.com/repos/{UPSTREAM}/commits/{target or 'main'}")
    return ref["sha"].lower()


def patch_ipa(original: bytes, build_version: str):
    zin = zipfile.ZipFile(io.BytesIO(original), "r")
    infos = zin.infolist()
    main_info_names = [i.filename for i in infos if re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", i.filename)]
    if len(main_info_names) != 1:
        raise RuntimeError(f"Expected exactly one main app Info.plist, found: {main_info_names}")
    main_info_name = main_info_names[0]
    main_plist = plistlib.loads(zin.read(main_info_name))
    bundle_id = main_plist.get("CFBundleIdentifier")
    version = main_plist.get("CFBundleShortVersionString") or main_plist.get("CFBundleVersion")
    if bundle_id != EXPECTED_BUNDLE_ID:
        raise RuntimeError(f"Unexpected bundle id: {bundle_id!r}")
    if not version:
        raise RuntimeError("Main bundle has no version")

    names = {i.filename for i in infos}
    if not any("/Frameworks/SideStoreApp.framework/" in n for n in names):
        raise RuntimeError("SideStoreApp.framework not found; refusing to publish a standalone LiveContainer IPA")

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zout:
        for info in infos:
            data = zin.read(info.filename)
            should_patch = (
                info.filename == main_info_name
                or re.fullmatch(r"Payload/[^/]+\.app/PlugIns/[^/]+\.appex/Info\.plist", info.filename)
            )
            if should_patch:
                p = plistlib.loads(data)
                p["CFBundleVersion"] = build_version
                fmt = plistlib.FMT_BINARY if data.startswith(b"bplist00") else plistlib.FMT_XML
                data = plistlib.dumps(p, fmt=fmt, sort_keys=False)
            zout.writestr(info, data)
    zin.close()
    return out.getvalue(), str(version), str(bundle_id)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def save_json(path: Path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def main() -> int:
    release = gh_json(f"https://api.github.com/repos/{UPSTREAM}/releases/tags/{TAG}")
    assets = [a for a in release.get("assets", []) if a.get("name") == ASSET_NAME]
    if len(assets) != 1:
        raise RuntimeError(f"Expected one {ASSET_NAME}, found {len(assets)}")
    asset = assets[0]
    commit = find_upstream_commit(release)
    updated_at = asset.get("updated_at") or release.get("published_at") or release.get("created_at")
    if not updated_at:
        raise RuntimeError("Upstream release has no usable timestamp")
    stamp = parse_iso(updated_at)
    build_version = stamp.strftime("%Y%m%d%H%M%S")
    fingerprint = f"{commit}:{asset.get('id')}:{updated_at}:{asset.get('size')}"

    state = load_json(STATE_PATH, {})
    if state.get("lastFingerprint") == fingerprint:
        print("No upstream change.")
        print("changed=false")
        return 0

    original = download(asset["browser_download_url"])
    if asset.get("size") and len(original) != int(asset["size"]):
        raise RuntimeError(f"Download size mismatch: got {len(original)}, expected {asset['size']}")
    upstream_sha = sha256(original)

    patched, marketing_version, bundle_id = patch_ipa(original, build_version)
    patched_sha = sha256(patched)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_IPA.write_bytes(patched)

    short = commit[:7]
    release_tag = f"nightly-{short}-{build_version}"
    download_url = f"https://github.com/{REPO}/releases/download/{release_tag}/{ASSET_NAME.replace('+', '%2B')}"
    description = (
        f"Official LC+SS nightly mirror of LiveContainer/LiveContainer commit {short}. "
        f"Only CFBundleVersion was changed to {build_version} so SideStore can detect nightly updates. "
        f"Upstream SHA-256: {upstream_sha}."
    )

    source = load_json(SOURCE_PATH, {})
    versions = []
    if source.get("apps"):
        versions = list(source["apps"][0].get("versions") or [])
    new_version = {
        "version": marketing_version,
        "buildVersion": build_version,
        "date": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "localizedDescription": description,
        "downloadURL": download_url,
        "size": len(patched),
        "sha256": patched_sha,
        "minOSVersion": "15.0"
    }
    versions = [v for v in versions if v.get("buildVersion") != build_version]
    versions.insert(0, new_version)
    versions = versions[:KEEP_VERSIONS]

    app = {
        "name": "LiveContainer + SideStore (Nightly)",
        "bundleIdentifier": bundle_id,
        "developerName": "LiveContainer Team",
        "subtitle": "Official LC+SS nightly, update-detectable mirror",
        "localizedDescription": "Mirrors the official LiveContainer+SideStore nightly. The executable code is unchanged; only CFBundleVersion is made unique per upstream nightly asset so SideStore can offer updates.",
        "iconURL": "https://raw.githubusercontent.com/LiveContainer/LiveContainer/main/screenshots/AppIcon1024.png",
        "tintColor": "#0784FC",
        "category": "utilities",
        "version": marketing_version,
        "buildVersion": build_version,
        "versionDate": new_version["date"],
        "versionDescription": description,
        "downloadURL": download_url,
        "size": len(patched),
        "versions": versions,
    }
    source.update({
        "name": "LC+SS Nightly (Atticus2077)",
        "identifier": "com.atticus2077.lcssnightly",
        "website": "https://github.com/LiveContainer/LiveContainer",
        "subtitle": "LiveContainer + SideStore official nightly mirror",
        "description": "Tracks the official LiveContainer+SideStore nightly and assigns a unique buildVersion so SideStore can detect same-version nightly updates.",
        "tintColor": "#0784FC",
        "iconURL": "https://raw.githubusercontent.com/LiveContainer/LiveContainer/main/screenshots/AppIcon1024.png",
        "apps": [app],
        "news": [],
    })
    save_json(SOURCE_PATH, source)

    state.update({
        "upstream": UPSTREAM,
        "tag": TAG,
        "asset": ASSET_NAME,
        "lastFingerprint": fingerprint,
        "upstreamCommit": commit,
        "upstreamAssetId": asset.get("id"),
        "upstreamAssetUpdatedAt": updated_at,
        "upstreamSHA256": upstream_sha,
        "patchedSHA256": patched_sha,
        "marketingVersion": marketing_version,
        "buildVersion": build_version,
        "releaseTag": release_tag,
        "size": len(patched),
    })
    save_json(STATE_PATH, state)

    meta = {
        "changed": True,
        "release_tag": release_tag,
        "commit": commit,
        "short_commit": short,
        "marketing_version": marketing_version,
        "build_version": build_version,
        "upstream_sha256": upstream_sha,
        "patched_sha256": patched_sha,
        "asset_size": len(patched),
    }
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
