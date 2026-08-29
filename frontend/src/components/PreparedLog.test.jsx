import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import PreparedLog from './PreparedLog'

const recipe = (overrides = {}) => ({
  last_prepared_on: null,
  prepared_count: 0,
  prepared_events: [],
  ...overrides,
})

describe('PreparedLog', () => {
  it('says never recorded when there is no history', () => {
    render(<PreparedLog recipe={recipe()} canEdit={false} onMark={vi.fn()} onDelete={vi.fn()} />)
    expect(screen.getByText('Never recorded as made.')).toBeDefined()
  })

  it('summarises the count and last-made date when there is history', () => {
    render(
      <PreparedLog
        recipe={recipe({ last_prepared_on: '2026-01-01T00:00:00Z', prepared_count: 3 })}
        canEdit={false}
        onMark={vi.fn()}
        onDelete={vi.fn()}
      />
    )
    expect(screen.getByText(/3 times in total/)).toBeDefined()
  })

  it('uses the singular for exactly one prep', () => {
    render(
      <PreparedLog
        recipe={recipe({ last_prepared_on: '2026-01-01T00:00:00Z', prepared_count: 1 })}
        canEdit={false}
        onMark={vi.fn()}
        onDelete={vi.fn()}
      />
    )
    expect(screen.getByText(/1 time in total/)).toBeDefined()
  })

  it('hides the "I made this" button and delete controls when canEdit is false', () => {
    render(
      <PreparedLog
        recipe={recipe({ prepared_events: [{ id: 1, prepared_on: '2026-01-01', rating: null, note: null }] })}
        canEdit={false}
        onMark={vi.fn()}
        onDelete={vi.fn()}
      />
    )
    expect(screen.queryByRole('button', { name: 'I made this' })).toBeNull()
    expect(screen.queryByTitle('Remove this entry')).toBeNull()
  })

  it('opens the form, submits it, and resets afterwards', async () => {
    const onMark = vi.fn().mockResolvedValue(undefined)
    render(<PreparedLog recipe={recipe()} canEdit onMark={onMark} onDelete={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'I made this' }))
    fireEvent.change(screen.getByPlaceholderText(/Note/), { target: { value: 'Halved the sugar' } })
    fireEvent.change(screen.getByDisplayValue('No rating'), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Record it' }))

    await waitFor(() => expect(onMark).toHaveBeenCalled())
    expect(onMark.mock.calls[0][0]).toMatchObject({ rating: 5, note: 'Halved the sugar' })
    // The form collapses again after a successful submit.
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Record it' })).toBeNull())
  })

  it('sends null rating and note when left blank', async () => {
    const onMark = vi.fn().mockResolvedValue(undefined)
    render(<PreparedLog recipe={recipe()} canEdit onMark={onMark} onDelete={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'I made this' }))
    fireEvent.click(screen.getByRole('button', { name: 'Record it' }))

    await waitFor(() => expect(onMark).toHaveBeenCalled())
    expect(onMark.mock.calls[0][0]).toMatchObject({ rating: null, note: null })
  })

  it('lists past events with rating and note, and deletes one on click', () => {
    const onDelete = vi.fn()
    render(
      <PreparedLog
        recipe={recipe({
          prepared_events: [{ id: 42, prepared_on: '2026-01-01T00:00:00Z', rating: 4, note: 'Great' }],
        })}
        canEdit
        onMark={vi.fn()}
        onDelete={onDelete}
      />
    )
    expect(screen.getByText('★★★★')).toBeDefined()
    expect(screen.getByText('Great')).toBeDefined()

    fireEvent.click(screen.getByTitle('Remove this entry'))
    expect(onDelete).toHaveBeenCalledWith(42)
  })
})
