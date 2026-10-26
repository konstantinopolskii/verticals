import type { Meta, StoryObj } from '@storybook/react-vite'
import { KCard, KCardStack, KCheckbox } from '../kit'

const meta = { title: 'Design/Vertical board', parameters: { layout: 'fullscreen' } } satisfies Meta

export default meta
type Story = StoryObj<typeof meta>

const columns = [
  { kind: 'Day', title: 'Today', goals: ['Easy 5 km', 'Buy gels'] },
  { kind: 'Week', title: '2–8 Mar', goals: ['Three runs', 'Book the race', 'New shoes'], active: true },
  { kind: 'Month', title: 'March', goals: ['12 runs, no injuries'] },
]

export const Columns: Story = {
  render: () => (
    <KCardStack className="pattern-vertical-board" style={{ height: 360 }}>
      {columns.map((column) => (
        <section key={column.kind} className={column.active ? 'pattern-vertical-board__column pattern-vertical-board__column--active' : 'pattern-vertical-board__column'}>
          <header className="pattern-vertical-board__header">
            <span className="t-caption t-muted">{column.kind}</span>
            <h2 className="t-title">{column.title}</h2>
          </header>
          <div className="pattern-vertical-board__body">
            <KCardStack dense>
              {column.goals.map((goal, i) => (
                <KCard key={goal} dense><KCheckbox modelValue={i === 0 && !!column.active} /><p className="t-caption">{goal}</p></KCard>
              ))}
            </KCardStack>
          </div>
        </section>
      ))}
    </KCardStack>
  ),
}
