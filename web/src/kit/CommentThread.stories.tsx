import type { Meta, StoryObj } from '@storybook/react-vite'
import { KCommentThread } from './components'

const meta = {
  title: 'Kit/Comment thread',
  component: KCommentThread,
  args: {
    title: 'Shorter intro?',
    messages: [
      { id: '1', body: 'The first paragraph repeats the title. Cut it?' },
      { id: '2', body: 'Cut. The second one says it better.', role: 'agent' },
    ],
  },
  decorators: [(Story) => <div style={{ maxWidth: 320 }}><Story /></div>],
} satisfies Meta<typeof KCommentThread>

export default meta
type Story = StoryObj<typeof meta>

export const Minimized: Story = {}
export const Active: Story = { args: { state: 'active' } }
export const Archived: Story = { args: { state: 'active', archived: true } }
