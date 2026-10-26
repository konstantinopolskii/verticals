import type { Meta, StoryObj } from '@storybook/react-vite'
import { KCheckbox } from './components'

const meta = {
  title: 'Kit/Checkbox',
  component: KCheckbox,
} satisfies Meta<typeof KCheckbox>

export default meta
type Story = StoryObj<typeof meta>

export const Unchecked: Story = {}
export const Checked: Story = { args: { modelValue: true } }
export const WithLabel: Story = { args: { label: 'Repeat every week' } }
