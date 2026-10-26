import type { Meta, StoryObj } from '@storybook/react-vite'
import { InboxCard } from './InboxCard'

const item = {
  id: 'goal-1',
  title: 'Buy running shoes',
  parent: { id: 'goal-0', title: 'Run a half marathon' },
  value_color: '#b5d6f2',
  parked_from_vertical: null,
  created_at: '2026-03-04T10:30:00Z',
  body_chars: 0,
  origin: 'inbox',
  private: false,
}

const meta = {
  title: 'App/Inbox card',
  component: InboxCard,
  args: { item },
  decorators: [(Story) => <div style={{ maxWidth: 360 }}><Story /></div>],
} satisfies Meta<typeof InboxCard>

export default meta
type Story = StoryObj<typeof meta>

export const WithGoal: Story = {}
export const Finding: Story = { args: { finding: true } }
export const NoGoal: Story = { args: { item: { ...item, parent: null, value_color: null } } }
export const LongTitle: Story = {
  args: { item: { ...item, title: 'Find a coach who can look at my running form and suggest drills for the winter months' } },
}
