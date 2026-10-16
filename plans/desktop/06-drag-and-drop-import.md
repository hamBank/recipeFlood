# Plan 6 — Drag-and-drop photo import (bonus)

## Goal

Drop an image file onto the photo inputs instead of browsing for it. That
covers the Import page's photo mode and the recipe form's Photo field. It
works on the website as well as in the desktop app. In the desktop app, a
file dropped anywhere else must not navigate the window away.

## Facts from the code

- `frontend/src/pages/ImportPage.jsx:~108–119`: in photo mode, a
  `<label>` wraps `<input type="file" accept="image/jpeg,image/png,image/webp,image/gif">`
  with `onChange={(event) => setFile(event.target.files?.[0] || null)}`.
  The help text says "JPEG, PNG, WebP or GIF, up to 8MB".
- `frontend/src/pages/RecipeFormPage.jsx:~404–409`: a `Field label="Photo"`
  wraps the same input with `setImageFile(...)`.
- **Tauri:** while a window's `dragDropEnabled` is `true` (plan 3 left it
  on), Tauri intercepts OS file drops for its own events, and the
  webview's HTML5 `drop` never fires. That's certainly true on Windows
  WebView2. HTML5 drag-and-drop needs `dragDropEnabled: false`.
- **Default webview behaviour:** dropping a file outside any drop target
  navigates the page to that file, which in the desktop app means the
  whole UI disappears.

## Changes

### 1. `frontend/src/components/ImageDropZone.jsx` (new)

Wrap the existing input. Don't replace it, because keyboard and
click-to-browse must keep working exactly as now.

- **Props:** `accept`, a comma list matching the input's `accept`;
  `onFile(file)`; `children`, the existing input and help text.
- **`onDragOver`/`onDragEnter`:** `preventDefault()` and show a
  highlighted dashed border with the existing theme tokens (look at how
  `index.css` and other components style borders and accents).
- **`onDragLeave`:** clear the highlight, minding child elements; a
  counter or `relatedTarget` check works.
- **`onDrop`:** `preventDefault()`, then take the first file from
  `dataTransfer.files`.
  - If its type is in `accept`, call `onFile(file)`.
  - Otherwise show an inline message: "That's not a JPEG, PNG, WebP or GIF
    image."
  - Several files: use the first, plus a short note "Only the first image
    was used." Neither page takes more than one.
- **Show the chosen file's name.** A dropped file doesn't populate the
  `<input>`'s own label. Match the existing visual language. If the input
  already shows nothing special, a small "Selected: name.jpg" line is
  enough.
- **The 8 MB limit:** if the existing pages enforce it client-side, the
  drop path goes through the same check. Grep for it; if it's only
  enforced server-side, leave it there.

### 2. Use it

- `ImportPage.jsx`: wrap the photo `<label>`, with `onFile={setFile}`.
- `RecipeFormPage.jsx`: wrap the Photo field's input, with
  `onFile={setImageFile}`.
- A file chosen by either method replaces the other, so the state stays
  single.

### 3. Desktop

- **`desktop/src-tauri/tauri.conf.json`:** set the window's
  `dragDropEnabled: false`, with a comment saying why: HTML5 drop events
  only reach the webview with it off.
- **`frontend/src/desktop.js`, `installDropGuard()`:** called from
  `main.jsx` in desktop mode next to `installExternalLinkHandler`. It adds
  document-level `dragover` and `drop` listeners that `preventDefault()`
  unless the event is inside an `ImageDropZone`, marked by a
  `data-dropzone` attribute. That stops a stray drop from replacing the
  app with the image.
- **Web stays as browsers already behave:** no global guard there, because
  that wouldn't keep behaviour unchanged. The zones themselves work on web.

## Tests

Vitest with Testing Library. Build `dataTransfer` objects with
`{ files: [file], types: ['Files'] }` and use `fireEvent.drop`.

- **ImageDropZone:**
  - An accepted file calls `onFile`.
  - A rejected type shows the message and doesn't call `onFile`.
  - Several files use the first and show the note.
  - The highlight goes on with dragenter and off with dragleave or drop.
- **ImportPage and RecipeFormPage:**
  - Dropping a file enables Import or sets the photo, the same as choosing
    it.
  - Submitting sends the dropped file through the existing
    `importFromImage` or `uploadRecipeImage` mocks.
- **Drop guard:**
  - Desktop mode: a drop outside a zone has `defaultPrevented`, and a drop
    inside a zone is handled by the zone.
  - Web mode: the guard isn't installed.
- Existing tests for both pages still pass untouched.

## Verify

Run the README baseline, then:

```bash
(cd desktop && npx tauri build --bundles deb)
xvfb-run -a timeout 20 desktop/src-tauri/target/release/recipe-flood; test $? -eq 124
```

Real OS drag-and-drop can't be automated here. Report it for a manual
check on Windows, where WebView2 is the case that matters:

1. Drag a photo from Explorer onto Import, then Photo.
2. Drag a photo onto an empty area: nothing should happen.

## Acceptance

- [ ] Dropping an image works on both inputs, on the website and in the
      desktop app.
- [ ] Wrong types and multiple files are handled with clear inline
      messages.
- [ ] Click-to-browse and keyboard use are unchanged.
- [ ] In the desktop app, a stray drop never navigates away.
- [ ] SPEC.md mentions drag-and-drop where the import and photo features
      are described.

## Out of scope

Pasting images from the clipboard; multi-image import; dropping onto other
parts of the app.
