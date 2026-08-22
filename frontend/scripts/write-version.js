#!/usr/bin/env node
// Writes public/version.json before `vite build` runs, so Vite copies it
// into backend/static/. Lets /health report which commit the served
// frontend bundle was built from (see backend/version.py) — the same
// signal that catches a partial deploy (backend restarted without a
// frontend rebuild, or vice versa) before a user reports a stale page.
import { execSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDir = dirname(fileURLToPath(import.meta.url))
const publicDir = join(scriptDir, '..', 'public')

let version = 'unknown'
try {
  version = execSync('git rev-parse --short HEAD', { cwd: scriptDir })
    .toString()
    .trim()
} catch {
  // Not a git checkout (e.g. a tarball build) — leave as 'unknown'.
}

mkdirSync(publicDir, { recursive: true })
writeFileSync(
  join(publicDir, 'version.json'),
  JSON.stringify({ version, built_at: new Date().toISOString() }, null, 2) + '\n',
)
console.log(`wrote public/version.json (${version})`)
