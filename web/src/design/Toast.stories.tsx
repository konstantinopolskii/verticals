import type { Meta, StoryObj } from '@storybook/react-vite'

const meta = { title: 'Design/Toast', parameters: { layout: 'fullscreen' } } satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

function Toast({ text, action, state = 'open' }: { text: string; action?: string; state?: string }) {
  return (
    <div className="toast" role="status" data-state={state}>
      <span className="toast__text">{text}</span>
      {action ? <button type="button" className="toast__action">{action}</button> : null}
      <button type="button" className="toast__close" aria-label="Dismiss">×</button>
    </div>
  )
}

const frame = (children: React.ReactNode) => <div style={{ height: 240 }}><div className="toast-stack">{children}</div></div>

export const Message: Story = { render: () => frame(<Toast text="Goal moved to next week" />) }
export const WithAction: Story = { render: () => frame(<Toast text="Goal deleted" action="Undo" />) }
export const Stacked: Story = { render: () => frame(<><Toast text="Saved" /><Toast text="Goal deleted" action="Undo" /></>) }
export const Closing: Story = { render: () => frame(<Toast text="Goal deleted" action="Undo" state="closed" />) }
