import type { Meta, StoryObj } from '@storybook/react-vite'
import { DocChip } from './DocChip'

const doc = {
  id: 'doc-1',
  title: 'Half marathon plan',
  path: 'plans/half-marathon.md',
  excerpt: '# Half marathon plan\n\nThree runs a week: two easy, one long. The long run grows by a kilometre each week.',
  created_at: '2026-03-02T09:00:00Z',
  updated_at: '2026-03-04T10:30:00Z',
}

const meta = {
  title: 'App/Doc chip',
  component: DocChip,
  args: { id: doc.id, doc },
} satisfies Meta<typeof DocChip>

export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {}
export const OnMessage: Story = {
  args: { dark: true },
  decorators: [(Story) => <div style={{ background: '#000', padding: 16, display: 'inline-block' }}><Story /></div>],
}
export const Untitled: Story = { args: { doc: { ...doc, title: '' } } }
export const SourceChecked: Story = { args: { note: 'checked 07:00', tone: 'ok' } }
export const SourceDown: Story = { args: { note: 'not answering since 06:00', tone: 'red' } }
