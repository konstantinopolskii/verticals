import type { Meta, StoryObj } from '@storybook/react-vite'

const meta = { title: 'Design/Typography' } satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

export const Scale: Story = {
  render: () => (
    <div style={{ display: 'grid', gap: 12, maxWidth: 560 }}>
      <h1 className="t-hero">Run a half marathon</h1>
      <h2 className="t-title">Week by week</h2>
      <p className="t-subtitle">Three runs a week</p>
      <p className="t-body">Two easy runs and one long run. The long run grows by a kilometre each week.</p>
      <p className="t-caption">Rest on Mondays.</p>
      <p className="t-caption t-muted">Edited 4 Mar</p>
      <p className="t-caption">Pace is <code className="t-code">time / distance</code>.</p>
      <pre className="t-code--block">{'pace = time / distance\nsplits = [5, 6, 10]'}</pre>
    </div>
  ),
}
export const Lists: Story = {
  render: () => (
    <div style={{ display: 'grid', gap: 24, maxWidth: 360 }}>
      <ul className="t-list"><li>Buy gels</li><li>New shoes</li><li>Book the race</li></ul>
      <ol className="t-list"><li>Easy 5 km</li><li>Tempo 6 km</li><li>Long run</li></ol>
      <div className="card"><div className="card__heading"><h3 className="t-title">In a card</h3></div><ul className="t-list"><li>Buy gels</li><li>New shoes</li></ul></div>
    </div>
  ),
}
export const Placeholders: Story = {
  render: () => (
    <div style={{ display: 'grid', gap: 12, maxWidth: 320 }}>
      <input placeholder="Search goals" />
      <textarea placeholder="Notes" />
      <p hidden>Hidden paragraph</p>
    </div>
  ),
}
