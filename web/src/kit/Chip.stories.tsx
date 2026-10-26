import type { Meta, StoryObj } from '@storybook/react-vite'
import { KChip } from './components'

const meta = {
  title: 'Kit/Chip',
  component: KChip,
  args: { children: 'Week' },
} satisfies Meta<typeof KChip>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {}
export const Pressed: Story = { args: { pressed: true } }
