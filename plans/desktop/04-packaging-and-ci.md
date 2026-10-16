# Plan 4 — Packaging and CI

## Goal

Build Windows and Linux installers in GitHub Actions:

- **Every PR that touches the desktop app or the frontend:** a build check
  on both OSes.
- **A `desktop-vX.Y.Z` tag:** a draft GitHub Release with the installers
  attached. The owner reviews and publishes it.

The installers are unsigned, by decision; document the SmartScreen step.

## Before you start

Plan 3 is merged. Read `.github/workflows/ci.yml` and match its style:
pinned major versions and comments explaining why a job exists.

GitHub release downloads are blocked in this container, so AppImage
bundling can't run locally, because it fetches linuxdeploy. Only CI can
prove the AppImage and Windows builds. Locally, verify the `.deb` and the
workflow's syntax.

## Changes

### 1. `.github/workflows/desktop.yml` (new)

- **Triggers:**
  - `pull_request` with `paths: [desktop/**, frontend/**, .github/workflows/desktop.yml]`.
    Frontend changes can break the desktop build, so they're included.
  - `push: tags: ['desktop-v*']`.
  - `workflow_dispatch`.
- **`build` job:** matrix `os: [ubuntu-22.04, windows-latest]`.
  Ubuntu 22.04 rather than latest, so the `.deb` and AppImage run on older
  glibc too; say so in a comment.
  - Check out, then run `actions/setup-node@v4` (node 22, npm cache for
    both lockfiles), `dtolnay/rust-toolchain@stable` and
    `Swatinem/rust-cache@v2` with `workspaces: desktop/src-tauri`.
  - On Ubuntu, install the apt packages from plan 3.
  - `npm ci` in `frontend/` and in `desktop/`.
  - `cargo test` in `desktop/src-tauri`.
  - Run `tauri-apps/tauri-action@v0` with `projectPath: desktop`.
    - **On tags:** `tagName: ${{ github.ref_name }}`,
      `releaseName: 'Recipe Flood desktop v__VERSION__'`,
      `releaseDraft: true`, and `releaseBody` linking DEPLOYMENT.md's
      install notes.
    - **Otherwise:** no release fields, then upload
      `desktop/src-tauri/target/release/bundle/**` with
      `actions/upload-artifact@v4`, named per OS, kept 7 days.
  - **Permissions:** `contents: write` only where a release is created.
    Read-only otherwise.
- **`version-check` job**, tags only, runs before `build`. It fails unless
  the tag's `X.Y.Z` equals the version in `tauri.conf.json`,
  `desktop/package.json` and `desktop/src-tauri/Cargo.toml`. Use a small
  inline script with node or python and a clear message on mismatch.

### 2. Bundle config (`tauri.conf.json`)

- **Targets:** `deb`, `appimage`, `nsis`, `msi`.
- **Windows:** `webviewInstallMode: downloadBootstrapper`, which is the
  default; state it explicitly with a comment. NSIS `installMode:
  currentUser`, so no admin prompt is needed.
- **Linux deb:** declare the `libwebkit2gtk-4.1-0` dependency if Tauri
  doesn't infer it. Check the generated control file.
- **Metadata:** publisher "hamBank", short description, category
  "Lifestyle". No certificate fields.

### 3. Docs

- **DEPLOYMENT.md, "Desktop releases":**
  - Bump the version in the three files.
  - Push the tag `desktop-vX.Y.Z`.
  - Wait for the workflow, then review and publish the draft release.
  - Installing:
    - Windows: run the `.exe` (NSIS) or `.msi`. SmartScreen says "Windows
      protected your PC", so click **More info → Run anyway**. That's
      expected, because the installer is unsigned.
    - Linux: `sudo apt install ./Recipe.Flood_X.Y.Z_amd64.deb`, or
      `chmod +x` the AppImage and run it.
  - The app's server defaults to production. Change it in Settings.
- **README.md:** a short "Desktop app" line linking to that section.

## Tests and verification

```bash
# locally
(cd desktop && npm ci && npx tauri build --bundles deb)
dpkg-deb -I desktop/src-tauri/target/release/bundle/deb/*.deb   # check Depends: and metadata
python - <<'EOF'   # workflow parses as YAML and has the expected jobs
import yaml; w = yaml.safe_load(open('.github/workflows/desktop.yml'))
print(sorted(w['jobs'])); print(w[True] if True in w else w['on'])
EOF
# version-check script: run it by hand with a matching and a mismatching fake tag
```

Run the full baseline from the README.

**CI is the real test.** The orchestrator opens the PR and both matrix legs
must go green. Then it lists the uploaded artifacts:

- Ubuntu: a `.deb` and an `.AppImage`;
- Windows: an NSIS `.exe` and an `.msi`.

If a leg fails, the orchestrator reads the job log and fixes the cause.
Never skip a target to get green.

**Releases are the owner's call.** The orchestrator does not push a
`desktop-v*` tag unless the owner says to. Once the owner agrees, the
first one is `desktop-v0.1.0`.

## Acceptance

- [ ] On a PR, both OSes build and upload the four installer types.
- [ ] On a tag, the version check runs and a draft release is created
      with the installers attached. Proved on the first real tag, with the
      owner's go-ahead.
- [ ] No signing configuration, and no secrets needed for this plan.
- [ ] DEPLOYMENT.md explains releasing and installing, including the
      SmartScreen step.

## Out of scope

Auto-update (plan 5), code signing, macOS, and a Microsoft Store or
Flathub listing.
