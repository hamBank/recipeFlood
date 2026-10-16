# Plan 5 — Auto-update

## Goal

Installed copies notice a newer published release and offer to update
themselves:

- **Windows** (NSIS or MSI): download, install and restart.
- **Linux AppImage:** download, replace and restart.
- **Linux `.deb`:** can't self-update, so show a link to the release page.

## Owner action required first

Tauri's updater only installs updates signed with a key whose public half
is baked into the app. **The owner creates the key on their own machine.**
The private key must never be in this repo or in a session transcript.

```bash
cd desktop && npx tauri signer generate -w ~/.tauri/recipeflood-updater.key
```

Then add two GitHub repo secrets under Settings → Secrets and variables →
Actions:

- `TAURI_SIGNING_PRIVATE_KEY`: the contents of the `.key` file.
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`: the password chosen.

Finally, give the orchestrator the **public** key. That's the `.key.pub`
file's contents, and it's safe to share and commit.

**Don't start this plan until the owner confirms that the secrets exist and
has supplied the public key.** If either is missing, stop and say so. Don't
generate a key yourself as a workaround.

## Changes

### 1. Rust and config

- **Plugins:** `tauri-plugin-updater` and `tauri-plugin-process` (for
  relaunch). Capabilities grant `updater:default` and
  `process:allow-restart`.
- **`tauri.conf.json`:**
  - `bundle.createUpdaterArtifacts: true`.
  - `plugins.updater.pubkey`: the owner's public key.
  - `plugins.updater.endpoints`:
    `["https://github.com/hamBank/recipeFlood/releases/latest/download/latest.json"]`.
  - `plugins.updater.windows.installMode: "passive"`.
- **The `releases/latest` caveat:** that URL resolves to the repo's newest
  *published, non-prerelease* release. Check the repo's existing releases
  and tags. If anything other than desktop releases is published there,
  say so and propose an alternative endpoint, such as a fixed
  `desktop-latest` release that the workflow updates, rather than
  guessing.
- **Rust command `install_kind() -> "appimage" | "deb" | "windows" | "other"`:**
  - `appimage` when the `APPIMAGE` env var is set on Linux;
  - `deb` for any other Linux install;
  - `windows` on Windows.

### 2. CI (`.github/workflows/desktop.yml`)

- Pass both secrets to `tauri-action` as env vars, on tag builds only.
- Set `includeUpdaterJson: true` so `latest.json` is attached to the
  release.
- PR builds stay unsigned and must not need the secrets, because forks and
  PRs can't read them. With `createUpdaterArtifacts` on and no key, the PR
  build would fail. Find the supported way to skip updater artifacts on PR
  builds, such as a config override passed via `--config` or `args`, and
  explain it in a comment.

### 3. Frontend (desktop only, dynamically imported like plan 3's code)

- **`frontend/src/updater.js`:**
  - `checkForUpdate()`:
    - **appimage or windows:** the updater plugin's `check()`. Returns
      `{version, notes, install}`, where `install` calls
      `downloadAndInstall` and then `relaunch()`.
    - **deb:** fetches nothing and returns `{manualUrl: releases page}`
      only if a newer version exists, comparing against the GitHub API's
      latest release tag. If that request fails, return nothing quietly.
- **An `UpdateBanner` component in the layout, desktop only.**
  - Check about 10 s after startup, then every 6 hours.
  - **Update available:** "Recipe Flood vX is available", with **Restart
    and update** and **Later** buttons.
  - **deb:** "Download vX" opens the release page through
    `openExternal`.
  - **Later:** hides the banner until the next start.
  - **Errors** (offline, GitHub down) are silent. Log them to the console
    only, never as an error banner.

## Tests

- **Vitest** (mock the plugin modules and `install_kind`):
  - The banner appears when an update exists.
  - Restart calls install, then relaunch.
  - Later hides it.
  - On deb, the download link uses `openExternal`.
  - A failed check shows nothing.
  - In web mode the banner doesn't render and nothing is imported.
- **Rust:** a unit test for `install_kind`'s env-var logic. Factor the
  logic into a pure function taking the env value.
- `cargo test`, the frontend baseline, and the local `.deb` build all
  still pass.

## Verify

The README baseline, `cargo test`, and a local `npx tauri build --bundles deb`
with updater artifacts disabled locally, the same way PR builds disable
them. Confirm the web bundle has no updater code.

**End to end, with the owner, after merge:**

1. Release `desktop-v0.1.1` with the secrets in place. Check that the
   release has `latest.json` and `.sig` files.
2. Install 0.1.0 on Windows.
3. Publish 0.1.1.
4. Start 0.1.0: the banner appears, and Restart lands on 0.1.1.

Report this as a pending manual step. It can't be done from here.

## Acceptance

- [ ] Signed updater artifacts and `latest.json` on tag builds. PR builds
      are still green without the secrets.
- [ ] Windows and AppImage installs update in place, and deb installs get a
      download link.
- [ ] No private key anywhere in the repo or the logs. The public key is in
      `tauri.conf.json`.
- [ ] DEPLOYMENT.md:
  - the key and secrets setup;
  - "if you lose the key, existing installs can't auto-update and must
    reinstall manually";
  - how a release reaches installed apps.

## Out of scope

Delta updates, update channels such as beta, and forced updates.
