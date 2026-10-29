import type { Meta, StoryObj } from '@storybook/react-vite'
import { KCheckbox } from '../kit'

const meta = { title: 'Design/Modal body' } satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

export const Editor: Story = {
  render: () => (
    <div className="modal__body" style={{ maxWidth: 480 }}>
      <KCheckbox size="xl" />
      <h1 className="t-hero">Run a half marathon</h1>
      <p>Three runs a week: two easy, one long.</p>
    </div>
  ),
}
