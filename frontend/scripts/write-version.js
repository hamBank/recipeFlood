#!/usr/bin/env node
// Writes public/version.json before `vite build` runs, so Vite copies it
// into the build output (fleet spec BLD-2). /health reports it (see
// backend/version.py), and the smoke check compares build_sha with the
// commit just deployed, so a skipped or failed build shows up as a
// mismatch instead of silently serving the old bundle.
//
//   build_sha     the commit that was built (HEAD)
//   frontend_sha  the last commit that changed frontend/src: baked into the
//                 bundle (vite.config.js) so an open tab can tell when the
//                 *frontend* changed, without every backend-only deploy
//                 asking it to reload
//
// No git checkout (a tarball, a container)? Pass BUILD_SHA (and optionally
// FRONTEND_SHA) instead. Never writes 'unknown' (fleet spec BLD-3).
import { execSync } from 'node:child_process'
import process from 'node:process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDir = dirname(fileURLToPath(import.meta.url))
const frontendDir = join(scriptDir, '..')
const publicDir = join(frontendDir, 'public')

const git = (args) =>
  execSync(`git ${args}`, { cwd: frontendDir, stdio: ['ignore', 'pipe', 'ignore'] })
    .toString()
    .trim()

let build = process.env.BUILD_SHA || ''
let frontend = process.env.FRONTEND_SHA || ''
try {
  if (!build) build = git('rev-parse --short HEAD')
  if (!frontend) frontend = git('log -1 --format=%h -- src')
} catch {
  // No git: fall through to the check below.
}
if (!build) {
  console.error('Cannot determine the commit being built: no git checkout and no BUILD_SHA')
  process.exit(1)
}

const version = { build_sha: build, frontend_sha: frontend || build, built_at: new Date().toISOString() }
mkdirSync(publicDir, { recursive: true })
writeFileSync(join(publicDir, 'version.json'), JSON.stringify(version, null, 2) + '\n')
console.log(`wrote public/version.json (build ${version.build_sha}, frontend ${version.frontend_sha})`)
