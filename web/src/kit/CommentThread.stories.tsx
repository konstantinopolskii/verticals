import type { Meta, StoryObj } from '@storybook/react-vite'
import { KCommentNew, KCommentStack, KCommentThread } from './components'

const messages = [
  { id: '1', body: 'The first paragraph repeats the title. Cut it?' },
  { id: '2', body: 'Cut. The second one says it better.', role: 'agent' },
  { id: '3', body: 'Done, thanks.' },
]

const meta = {
  title: 'Kit/Comment thread',
  component: KCommentThread,
  args: { title: 'Shorter intro?', messages },
  decorators: [(Story) => <div style={{ maxWidth: 320 }}><Story /></div>],
} satisfies Meta<typeof KCommentThread>

export default meta
type Story = StoryObj<typeof meta>

export const Minimized: Story = {}
export const Active: Story = { args: { state: 'active' } }
export const Resolved: Story = { args: { state: 'active', 'data-resolved': 'true' } }
export const Editing: Story = { args: { state: 'active', 'data-editing': 'true' } }
export const WithReply: Story = {
  render: () => (
    <div className="card-stack">
      {['', 'Sounds good'].map((value) => (
        <div key={value || 'empty'} className="card card--interactive comment-thread" data-state="active">
          <div className="card__heading"><h3 className="t-title">Shorter intro?</h3></div>
          <div className="card__collapsible"><div className="card__collapsible-inner">
            <div className="comment-msg"><p className="t-caption">The first paragraph repeats the title.</p></div>
          </div></div>
          <label className="field comment-thread__reply">
            <input className="t-caption field__input" type="text" placeholder="Reply…" defaultValue={value} />
          </label>
        </div>
      ))}
    </div>
  ),
}
export const NewComment: Story = {
  render: () => (
    <div className="card-stack">
      <KCommentNew placeholder="Write a comment…" commitLabel="Comment" />
      <KCommentNew placeholder="Write a comment…" commitLabel="Comment" modelValue="Should the long run move to Saturday?" data-state="active" />
    </div>
  ),
}
export const Stack: Story = {
  render: () => (
    <KCommentStack>
      <KCommentNew placeholder="Write a comment…" commitLabel="Comment" />
      <KCommentThread title="Shorter intro?" state="active" messages={messages} />
      <KCommentThread title="Rename the doc?" messages={messages.slice(0, 1)} />
      <KCommentThread title="Old note" archived messages={messages.slice(0, 1)} />
    </KCommentStack>
  ),
}
