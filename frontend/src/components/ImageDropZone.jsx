import { useRef, useState } from 'react'

const TYPE_LABELS = {
  'image/jpeg': 'JPEG',
  'image/png': 'PNG',
  'image/webp': 'WebP',
  'image/gif': 'GIF',
}

const hasFiles = (event) => Array.from(event.dataTransfer?.types || []).includes('Files')

/**
 * Lets an image be dropped onto a photo input. It wraps the page's own
 * `<input type="file">` rather than replacing it, so click-to-browse and
 * keyboard use are untouched; a drop is just another way to call `onFile`.
 *
 * `accept` is the input's own comma list. A dropped file bypasses the
 * input's `accept` filter, so the type is checked again here.
 */
export default function ImageDropZone({ accept, onFile, children }) {
  const wrapper = useRef(null)
  // dragenter/dragleave also fire for every child crossed, so a counter
  // (not a boolean) says when the pointer has really left the zone.
  const depth = useRef(0)
  const [active, setActive] = useState(false)
  const [dropped, setDropped] = useState(null)
  const [message, setMessage] = useState(null)

  const accepted = accept.split(',').map((type) => type.trim())
  const typeNames = accepted.map((type) => TYPE_LABELS[type] || type)
  const typeList = `${typeNames.slice(0, -1).join(', ')} or ${typeNames.at(-1)}`

  const enter = (event) => {
    if (!hasFiles(event)) return
    event.preventDefault()
    depth.current += 1
    setActive(true)
  }

  const over = (event) => {
    if (!hasFiles(event)) return
    event.preventDefault()
    event.dataTransfer.dropEffect = 'copy'
  }

  const leave = () => {
    depth.current = Math.max(0, depth.current - 1)
    if (depth.current === 0) setActive(false)
  }

  const drop = (event) => {
    if (!hasFiles(event)) return
    event.preventDefault()
    depth.current = 0
    setActive(false)

    const files = Array.from(event.dataTransfer.files || [])
    const [file] = files
    if (!file) return
    if (!accepted.includes(file.type)) {
      setMessage({ error: true, text: `That's not a ${typeList} image.` })
      return
    }
    // The input can't be given a file programmatically, so clear it rather
    // than leave it naming a different file from the one in use.
    const input = wrapper.current?.querySelector('input[type="file"]')
    if (input) input.value = ''
    setDropped(file.name)
    setMessage(files.length > 1 ? { text: 'Only the first image was used.' } : null)
    onFile(file)
  }

  // A file chosen with the input replaces a dropped one.
  const chose = () => {
    setDropped(null)
    setMessage(null)
  }

  return (
    <div
      ref={wrapper}
      data-dropzone
      onDragEnter={enter}
      onDragOver={over}
      onDragLeave={leave}
      onDrop={drop}
      onChange={chose}
      className={`-m-1 rounded-lg border border-dashed p-1 ${
        active ? 'border-accent bg-accent-soft' : 'border-transparent'
      }`}
    >
      {children}
      {dropped && <p className="mt-1 text-xs text-ink-muted">Selected: {dropped}</p>}
      {message && (
        <p className={`mt-1 text-xs ${message.error ? 'text-red-700' : 'text-ink-muted'}`}>
          {message.text}
        </p>
      )}
    </div>
  )
}
