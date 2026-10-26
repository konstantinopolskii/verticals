import type { Meta, StoryObj } from '@storybook/react-vite'
import { KField } from './components'

const meta = {
  title: 'Kit/Field',
  component: KField,
  args: { placeholder: 'Name the goal' },
  decorators: [(Story) => <div style={{ maxWidth: 320 }}><Story /></div>],
} satisfies Meta<typeof KField>

export default meta
type Story = StoryObj<typeof meta>

export const Empty: Story = {}
export const Filled: Story = { args: { modelValue: 'Run a half marathon' } }
export const Textarea: Story = { args: { textarea: true, modelValue: 'Three runs a week, one of them long.\nRest on Mondays.' } }
export const InCard: Story = {
  render: () => (
    <div className="card">
      <div className="card__heading"><h3 className="t-title">New goal</h3></div>
      <KField placeholder="Title" modelValue="Run a half marathon" />
      <KField placeholder="When" />
      <div className="card__heading"><h3 className="t-subtitle">Notes</h3></div>
      <KField textarea placeholder="Why it matters" />
    </div>
  ),
}
