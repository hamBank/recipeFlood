import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ImageDropZone from './ImageDropZone'

const ACCEPT = 'image/jpeg,image/png,image/webp,image/gif'
const image = (name = 'recipe.jpg', type = 'image/jpeg') => new File(['fake'], name, { type })
const transfer = (...files) => ({ dataTransfer: { files, types: ['Files'] } })

const onFile = vi.fn()

function renderZone() {
  render(
    <ImageDropZone accept={ACCEPT} onFile={onFile}>
      <label>
        Photo <input type="file" accept={ACCEPT} />
      </label>
    </ImageDropZone>
  )
  return document.querySelector('[data-dropzone]')
}

beforeEach(() => vi.clearAllMocks())

describe('ImageDropZone', () => {
  it('passes an accepted file to onFile and names it', () => {
    const zone = renderZone()
    const file = image()
    fireEvent.drop(zone, transfer(file))
    expect(onFile).toHaveBeenCalledWith(file)
    expect(screen.getByText('Selected: recipe.jpg')).toBeDefined()
  })

  it('refuses a file of the wrong type with a message', () => {
    const zone = renderZone()
    fireEvent.drop(zone, transfer(image('notes.pdf', 'application/pdf')))
    expect(onFile).not.toHaveBeenCalled()
    expect(screen.getByText("That's not a JPEG, PNG, WebP or GIF image.")).toBeDefined()
    expect(screen.queryByText(/Selected:/)).toBeNull()
  })

  it('uses the first of several files and says so', () => {
    const zone = renderZone()
    const first = image('first.jpg')
    fireEvent.drop(zone, transfer(first, image('second.png', 'image/png')))
    expect(onFile).toHaveBeenCalledTimes(1)
    expect(onFile).toHaveBeenCalledWith(first)
    expect(screen.getByText('Only the first image was used.')).toBeDefined()
  })

  it('highlights on dragenter and clears on dragleave or drop', () => {
    const zone = renderZone()
    const input = screen.getByLabelText('Photo')
    expect(zone.className).not.toContain('border-accent')

    fireEvent.dragEnter(zone, transfer())
    expect(zone.className).toContain('border-accent')

    // Crossing into a child fires leave on the zone then enter on the child.
    fireEvent.dragEnter(input, transfer())
    fireEvent.dragLeave(zone, transfer())
    expect(zone.className).toContain('border-accent')

    fireEvent.dragLeave(input, transfer())
    expect(zone.className).not.toContain('border-accent')

    fireEvent.dragEnter(zone, transfer())
    fireEvent.drop(zone, transfer(image()))
    expect(zone.className).not.toContain('border-accent')
  })

  it('ignores drags that carry no files', () => {
    const zone = renderZone()
    fireEvent.dragEnter(zone, { dataTransfer: { files: [], types: ['text/plain'] } })
    expect(zone.className).not.toContain('border-accent')
  })

  it('lets a file chosen with the input replace a dropped one', () => {
    const zone = renderZone()
    fireEvent.drop(zone, transfer(image()))
    fireEvent.change(screen.getByLabelText('Photo'), { target: { files: [image('other.png', 'image/png')] } })
    expect(screen.queryByText(/Selected:/)).toBeNull()
  })
})
