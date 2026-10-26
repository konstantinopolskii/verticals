import type { Meta, StoryObj } from '@storybook/react-vite'
import { KCard, KCardStack } from './components'

const meta = {
  title: 'Kit/Card',
  component: KCard,
  args: { children: <p className="t-caption">Plan the route for Saturday's long run</p> },
  decorators: [(Story) => <div style={{ maxWidth: 320 }}><Story /></div>],
} satisfies Meta<typeof KCard>

export default meta
type Story = StoryObj<typeof meta>

const runs = ['Easy 5 km', 'Tempo 6 km', 'Long run']

export const Default: Story = {}
export const Dense: Story = { args: { dense: true } }
export const Stack: Story = {
  render: () => <KCardStack>{runs.map((title) => <KCard key={title}><p className="t-caption">{title}</p></KCard>)}</KCardStack>,
}
export const DenseStack: Story = {
  render: () => <KCardStack dense>{runs.map((title) => <KCard key={title} dense><p className="t-caption">{title}</p></KCard>)}</KCardStack>,
}
export const Interactive: Story = {
  render: () => (
    <div className="card-stack">
      {[undefined, 'active'].map((state) => (
        <div key={state ?? 'rest'} className="card card--interactive" data-state={state}>
          <div className="card__heading"><h3 className="t-title">{state ? 'Open card' : 'Closed card'}</h3></div>
          <div className="card__collapsible">
            <div className="card__collapsible-inner">
              <div className="card__heading"><p className="t-caption t-muted">Two easy runs and one long run</p></div>
              <ul className="t-list"><li>Tuesday</li><li>Thursday</li><li>Sunday</li></ul>
            </div>
          </div>
        </div>
      ))}
    </div>
  ),
}
export const Shout: Story = {
  render: () => (
    <div className="card-stack">
      <div className="card card--shout"><div className="card__heading"><h3 className="t-title">Commit the plan</h3></div><p className="t-caption">Twelve weeks, three runs each.</p></div>
      <div className="card"><p className="t-caption">A card below it</p></div>
    </div>
  ),
}
