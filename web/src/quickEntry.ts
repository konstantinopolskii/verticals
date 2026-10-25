// The same surface and typography as SearchBar, in the native floating window.
import '@konstantinopolskii/design-system/vars.css'
import '@konstantinopolskii/design-system/style.css'
import './tokens.css'
import './base.css'
import './components/circleField.css'
import './quickEntry.css'

type Native = Window & {
  webkit?: { messageHandlers: { quickEntry: { postMessage(message: unknown): void } } }
  quickEntry?: { state(busy: boolean, error: string, clear?: boolean, action?: string): void; complete(action: string): void; focus(): void }
}
const host = window as Native
const field = document.querySelector('textarea')!
const shape = document.querySelector<HTMLElement>('.circle-field__shape')!
const status = document.querySelector<HTMLElement>('[role=status]')!
const bubble = document.querySelector<HTMLElement>('.quick-entry')!
const words = document.querySelector<HTMLElement>('.circle-field__words')!
let phase = 'typing'
let action = 'inbox'
let busy = false
const post = (message: unknown) => host.webkit?.messageHandlers.quickEntry.postMessage(message)
function resize(): void {
  field.style.height = '0px'
  const height = Math.min(216, Math.max(36, field.scrollHeight))
  field.style.height = height + 'px'
  const extra = phase === 'error' ? status.offsetHeight + 12 : 0
  words.style.bottom = 24 + extra + 'px'
  shape.style.height = height + 48 + extra + 'px'
  post({ action: 'resize', height: height + 48 + extra })
}
host.quickEntry = {
  state(working, error, clear = false, selectedAction) {
    if (selectedAction) action = selectedAction
    phase = error ? 'error' : working ? 'working' : 'typing'
    bubble.dataset.phase = phase
    busy = working
    field.readOnly = working
    status.textContent = error || (working ? (action === 'agent' ? 'Starting agent…' : 'Adding to Inbox…') : '')
    if (clear) field.value = ''
    resize()
    if (!working) field.focus()
  },
  complete(selectedAction) {
    busy = true
    field.readOnly = true
    phase = 'success'
    bubble.dataset.phase = phase
    status.textContent = selectedAction === 'agent' ? 'Sent to agent' : 'Added to Inbox'
    resize()
  },
  focus() { field.focus(); resize() },
}
field.addEventListener('input', resize)
field.addEventListener('keydown', (event) => {
  if (event.isComposing) return
  if (event.key === 'Escape' && (!busy || phase === 'success')) { event.preventDefault(); post({ action: 'cancel' }); return }
  if (event.key !== 'Enter' || event.shiftKey) return
  event.preventDefault()
  if (busy || !field.value.trim()) return
  action = event.metaKey ? 'agent' : 'inbox'
  host.quickEntry!.state(true, '', false, action)
  post({ action, text: field.value })
})
document.fonts.ready.then(() => { resize(); field.focus() })
