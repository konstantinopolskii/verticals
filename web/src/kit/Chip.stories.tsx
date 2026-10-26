import type { Meta, StoryObj } from '@storybook/react-vite'
import { KChip } from './components'

const meta = {
  title: 'Kit/Chip',
  component: KChip,
  args: { children: 'Week' },
} satisfies Meta<typeof KChip>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {}
export const Pressed: Story = { args: { pressed: true } }
export const Wrap: Story = {
  render: () => (
    <div className="chip-wrap" style={{ maxWidth: 260 }}>
      {['health', 'work', 'family', 'travel', 'reading'].map((tag, i) => <KChip key={tag} pressed={i === 1}>{tag}</KChip>)}
    </div>
  ),
}
