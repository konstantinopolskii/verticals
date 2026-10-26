import type { Meta, StoryObj } from '@storybook/react-vite'
import { KButton } from './components'

const meta = {
  title: 'Kit/Button',
  component: KButton,
  args: { children: 'Save' },
} satisfies Meta<typeof KButton>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {}
export const Primary: Story = { args: { primary: true } }
export const Caption: Story = { args: { caption: true, children: 'Show all' } }
