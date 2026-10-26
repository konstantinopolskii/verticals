import type { Meta, StoryObj } from '@storybook/react-vite'
import { KField } from './components'

const meta = {
  title: 'Kit/Field',
  component: KField,
  args: { label: 'Title', placeholder: 'Name the goal' },
} satisfies Meta<typeof KField>

export default meta
type Story = StoryObj<typeof meta>

export const Empty: Story = {}
export const Filled: Story = { args: { modelValue: 'Run a half marathon' } }
export const Row: Story = { args: { row: true, modelValue: 'Run a half marathon' } }
export const Textarea: Story = {
  args: { textarea: true, label: 'Notes', modelValue: 'Three runs a week, one of them long.\nRest on Mondays.' },
}
