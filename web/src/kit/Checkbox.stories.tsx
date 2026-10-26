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
export const Sizes: Story = {
  render: () => (
    <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
      {['s', 'xl', 'xxl'].map((size) => <KCheckbox key={size} size={size} />)}
      {['s', 'xl', 'xxl'].map((size) => <KCheckbox key={`${size}-on`} size={size} modelValue />)}
    </div>
  ),
}
