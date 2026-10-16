# Desktop app — implementation plans

A Windows + Linux desktop app for Recipe Flood, built with **Tauri 2**
around the existing React frontend and talking to the same REST API as
the website. One plan per agent run; each one leaves the repo green and
shippable on its own, and the web app behaves exactly as before after
every one of them.

Decisions already made (don't revisit them in a plan):

- **Tauri 2**, not Electron or a native rewrite — one React codebase for
  web and desktop.
- **Windows and Linux** only. No macOS target, no notarisation.
- **Unsigned** Windows installers — SmartScreen's one-time "unknown
  publisher" warning is accepted. No code-signing certificate.
- **No PWA-only fallback** — a real installed app is wanted.
- Drag-and-drop photo import is a bonus; tray icon, global hotkey,
  notifications and autostart are **out of scope**.

## The plans, in order

| # | Plan | Depends on | Can be verified here? |
|---|------|-----------|-----------------------|
| 1 | [Frontend portability](01-frontend-portability.md) | — | Yes, fully |
| 2 | [Backend: CORS + desktop sign-in handoff](02-backend-cors-and-handoff.md) | — | Yes, fully |
| 3 | [Tauri shell](03-tauri-shell.md) | 1, 2 | Linux build + smoke run under Xvfb |
| 4 | [Packaging + CI](04-packaging-and-ci.md) | 3 | Linux locally; Windows only in GitHub Actions |
| 5 | [Auto-update](05-auto-update.md) | 4, **plus a repo secret the owner adds by hand** | Partly |
| 6 | [Drag-and-drop photo import](06-drag-and-drop-import.md) (bonus) | 3 | Yes (web), Linux smoke |

Plans 1 and 2 touch different files and could run in either order, but run
them one at a time so each PR is reviewed against a green main.

## How each plan is run

1. The orchestrating session syncs its branch with `origin/main` and
   starts a fresh agent with the plan file's contents as its brief.
2. The agent implements the plan **in the working tree only** — it does
   not commit, push, or open a PR — then runs every command in the plan's
   *Verify* section and reports the output.
3. The orchestrator reviews the diff against the plan's *Acceptance*
   list, re-runs *Verify* itself, then commits, pushes, opens the PR and
   drives CI to green.
4. Only after that PR merges does the next plan start.

## Rules every plan inherits

- **The web app must not change behaviour.** Every existing pytest and
  vitest test still passes unmodified (a test may only change if the plan
  says so and says why). `npm run build` still writes the web bundle to
  `backend/static/`.
- **Match the surrounding code**: comment density and voice, naming,
  idioms. Comments explain *why*, the way the existing ones do.
- **Docs move with the code**: SPEC.md / API.md / DEVELOPMENT.md /
  DEPLOYMENT.md / ARCHITECTURE.md get updated in the same change when
  behaviour, endpoints, setup steps or layout change.
- **No secrets in the repo.** Signing keys, tokens and passwords go in
  GitHub secrets or the server's `/opt/recipeFlood/.env`, never in a
  committed file.
- **Don't widen scope.** Anything noticed but out of scope goes in the
  report as a follow-up, not into the diff.
- Baseline checks, run from the repo root unless noted:
  ```bash
  source .venv/bin/activate && rm -f recipeflood.db* && python -m pytest -q
  alembic upgrade head && alembic check && rm -f recipeflood.db*
  (cd frontend && npm run lint && npx vitest run && npm run build)
  ```
- The agent's final report lists: files changed, tests added, the exact
  output tail of every Verify command, and anything it could not verify
  (and why).
