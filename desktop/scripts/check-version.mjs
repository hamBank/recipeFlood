// Fails unless a release tag's X.Y.Z matches the version in all three
// files that carry one. They are bumped by hand, and a tag that disagrees
// with them would publish installers whose filenames and "About" version
// contradict the release.
//
//   node desktop/scripts/check-version.mjs desktop-v0.1.0
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const tag = process.argv[2] ?? "";

const m = /^desktop-v(\d+\.\d+\.\d+)$/.exec(tag);
if (!m) {
  console.error(`Tag "${tag}" is not of the form desktop-vX.Y.Z`);
  process.exit(1);
}
const want = m[1];

const read = (p) => readFileSync(join(root, p), "utf8");
// Cargo.toml: the first `version = "..."` is the [package] one, because
// [package] is the first table and dependency versions come later.
const cargo = /^version\s*=\s*"([^"]+)"/m.exec(read("src-tauri/Cargo.toml"));

const found = {
  "desktop/src-tauri/tauri.conf.json": JSON.parse(read("src-tauri/tauri.conf.json")).version,
  "desktop/package.json": JSON.parse(read("package.json")).version,
  "desktop/src-tauri/Cargo.toml": cargo && cargo[1],
};

let bad = false;
for (const [file, version] of Object.entries(found)) {
  const ok = version === want;
  if (!ok) bad = true;
  console.log(`${ok ? "ok      " : "MISMATCH"} ${file}: ${version} (tag says ${want})`);
}
if (bad) {
  console.error(`\nBump all three files to ${want} before tagging ${tag}.`);
  process.exit(1);
}
console.log(`\nAll three match ${want}.`);
