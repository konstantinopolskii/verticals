import type { Meta, StoryObj } from '@storybook/react-vite'

const meta = { title: 'Design/Dropdown' } satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

const items = ['Start work', 'Discuss', 'Move to next week', 'Delete']

function Menu({ state }: { state: 'open' | 'closed' }) {
  return (
    <div className="dropdown" style={{ position: 'relative', height: 220 }}>
      <button type="button" className="button t-subtitle dropdown__trigger" aria-expanded={state === 'open'}>Actions</button>
      <div className="dropdown__popover" role="menu" data-state={state} style={{ position: 'absolute', top: 48, left: 0 }}>
        <button type="button" className="dropdown__item" role="menuitem">Back</button>
        {items.map((item) => <button key={item} type="button" className="dropdown__item" role="menuitem">{item}</button>)}
        <button type="button" className="dropdown__item" role="menuitem" disabled>Open in…</button>
      </div>
    </div>
  )
}

export const Open: Story = { render: () => <Menu state="open" /> }
export const Closed: Story = { render: () => <Menu state="closed" /> }
