import type { Meta, StoryObj } from '@storybook/react-vite'
import { KInlineAdd } from './components'

const meta = {
  title: 'Kit/Inline add',
  component: KInlineAdd,
  args: { placeholder: 'Add tag…' },
  decorators: [(Story) => <div style={{ maxWidth: 260 }}><Story /></div>],
} satisfies Meta<typeof KInlineAdd>

export default meta
type Story = StoryObj<typeof meta>

export const Empty: Story = {}
export const Filled: Story = { args: { defaultValue: 'reading' } }
