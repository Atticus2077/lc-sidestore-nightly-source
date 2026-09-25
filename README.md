# LC+SS Nightly Source

Personal AltStore/SideStore source that tracks the official `LiveContainer+SideStore.ipa` nightly from `LiveContainer/LiveContainer`.

## Source URL

`https://raw.githubusercontent.com/Atticus2077/lc-sidestore-nightly-source/main/source.json`

## What this repository does

- Watches the official LiveContainer `nightly` release every 6 hours.
- Downloads only the official `LiveContainer+SideStore.ipa` asset.
- Validates the bundle is really LC+SS (`com.kdt.livecontainer` + `SideStoreApp.framework`).
- Changes only `CFBundleVersion` in the main app and app extensions to a monotonic timestamp derived from the upstream asset update time. This is necessary because upstream nightlies can keep the same marketing/build version (for example `3.8.10`) across several commits, which prevents SideStore from showing an update.
- Does not change code or `CFBundleShortVersionString`.
- Publishes the patched IPA as an immutable GitHub Release and updates `source.json`.
- Keeps a short rollback history in the source.

## Install / update

Add the Source URL above to the built-in SideStore. When a newer nightly appears, SideStore can detect it by `buildVersion` and offer Update.

For LC+SS, follow upstream guidance: install/update the IPA from the built-in SideStore; do not use the separate **Resign** button. If SideStore asks how to preserve extensions, use the upstream-recommended option that keeps all extensions with the main profile.

## Trust model

The workflow only accepts the `LiveContainer+SideStore.ipa` asset from the official `LiveContainer/LiveContainer` nightly release. `state.json` records upstream asset identity and SHA-256 plus the repacked IPA SHA-256 for auditability.
