import type { Meta, StoryObj } from '@storybook/react-vite'
import { KCard } from './components'

const meta = {
  title: 'Kit/Card',
  component: KCard,
  args: { children: <p className="t-caption">Plan the route for Saturday's long run</p> },
  decorators: [(Story) => <div style={{ maxWidth: 320 }}><Story /></div>],
} satisfies Meta<typeof KCard>

export default meta
type Story = StoryObj<typeof meta>

export const Static: Story = {}
export const Interactive: Story = { args: { variant: 'interactive' } }
export const Shout: Story = { args: { variant: 'shout' } }
export const Tight: Story = { args: { tight: true } }
