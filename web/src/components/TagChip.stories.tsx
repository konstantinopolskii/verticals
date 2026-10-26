import type { Meta, StoryObj } from '@storybook/react-vite'
import { TagChip } from './TagChip'

const meta = {
  title: 'App/Tag chip',
  component: TagChip,
  args: { tag: 'health' },
} satisfies Meta<typeof TagChip>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {}
export const Pressed: Story = { args: { pressed: true } }
export const Long: Story = { args: { tag: 'quarterly-review-with-the-whole-team' } }
