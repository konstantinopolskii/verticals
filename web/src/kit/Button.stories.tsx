import type { Meta, StoryObj } from '@storybook/react-vite'
import { KButton, KCard } from './components'

const meta = {
  title: 'Kit/Button',
  component: KButton,
  args: { children: 'Save' },
} satisfies Meta<typeof KButton>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {}
export const Primary: Story = { args: { primary: true } }
export const Disabled: Story = { args: { primary: true, disabled: true } }
export const InCard: Story = {
  render: () => (
    <div style={{ maxWidth: 320 }}>
      <KCard><p className="t-caption">Remove the sample goals?</p><KButton>Remove sample data</KButton></KCard>
    </div>
  ),
}
export const CallsToAction: Story = {
  render: () => (
    <div style={{ maxWidth: 320, display: 'grid', gap: 16 }}>
      {[undefined, 'active'].map((state) => (
        <div key={state ?? 'rest'} className="card card--interactive" data-state={state}>
          <div className="card__heading"><h3 className="t-title">{state ? 'Active card' : 'Card at rest'}</h3></div>
          <button type="button" className="button t-subtitle" data-cta="minimized">Open</button>
          <button type="button" className="button button--primary t-subtitle" data-cta="active">Commit</button>
        </div>
      ))}
    </div>
  ),
}
