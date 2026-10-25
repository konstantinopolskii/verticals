import { useLayoutEffect, useRef } from 'react'
import { tracked } from '../tracked'
import { keyboardGroups, keyboardHelpOpen } from '../lib/keyboard'
import { commandFilter } from '../lib/commandFilter'
import { store } from '../store'
import { AppIcon } from './AppIcon'
import './keyboardGuide.css'

function Keys({ values }: { values: string[] }) {
  return <span className="keyboard-guide__keys">{values.map((key) => <kbd key={key}>{key}</kbd>)}</span>
}

export const KeyboardGuide = tracked(function KeyboardGuide() {
  const dialog = useRef<HTMLDialogElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const previous = useRef<HTMLElement | null>(null)
  const selection = useRef<[number | null, number | null] | null>(null)
  const open = keyboardHelpOpen.value

  useLayoutEffect(() => {
    const guard = (event: KeyboardEvent) => {
      if (keyboardHelpOpen.value) event.stopImmediatePropagation()
    }
    window.addEventListener('keydown', guard, true)
    return () => window.removeEventListener('keydown', guard, true)
  }, [])

  useLayoutEffect(() => {
    const el = dialog.current
    if (!el) return
    if (open && !el.open) {
      previous.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
      const input = previous.current
      selection.current = input instanceof HTMLInputElement || input instanceof HTMLTextAreaElement
        ? [input.selectionStart, input.selectionEnd] : null
      el.showModal()
    } else if (!open && el.open) {
      el.close()
      const destination = previous.current?.isConnected ? previous.current : trigger.current
      destination?.focus({ preventScroll: true })
      if ((destination instanceof HTMLInputElement || destination instanceof HTMLTextAreaElement) && selection.current) {
        const [start, end] = selection.current
        if (start !== null && end !== null) destination.setSelectionRange(start, end)
      }
    }
  }, [open])

  const board = store.state.activeView === 'verticals' && store.state.openGoalVertical !== 'search'
  const group = (name: string) => {
    const definition = keyboardGroups.find((entry) => entry.name === name)!
    return <section className="keyboard-guide__group" aria-label={name}>
      <h3>{name}</h3>
      <dl>{definition.bindings.map(({ label, keys }) => <div className="keyboard-guide__binding" key={label}>
        <dt>{label}</dt><dd><Keys values={keys} /></dd>
      </div>)}</dl>
    </section>
  }
  const close = () => { keyboardHelpOpen.value = false }
  return <>
    <button ref={trigger} type="button" className="keyboard-help" aria-label="Keyboard shortcuts"
      aria-haspopup="dialog" data-open-region="keyboard-help" onPointerDown={(event) => event.preventDefault()}
      onClick={() => { keyboardHelpOpen.value = true }}><span aria-hidden="true">?</span><span>Keyboard shortcuts</span></button>
    <dialog ref={dialog} className="keyboard-guide" data-open-region="keyboard-help" aria-labelledby="keyboard-guide-title"
      aria-describedby="keyboard-guide-context" onCancel={(event) => { event.preventDefault(); close() }}
      onClose={close} onClick={(event) => {
        if (event.target !== event.currentTarget) return
        const box = event.currentTarget.getBoundingClientRect()
        if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) close()
      }}>
      <header className="keyboard-guide__head"><h2 id="keyboard-guide-title">Keyboard shortcuts</h2>
        <button type="button" aria-label="Close keyboard shortcuts" autoFocus onClick={close}><AppIcon name="x" size={20} /></button>
      </header>
      <p className="keyboard-guide__context" id="keyboard-guide-context">On the board · {board ? 'Press an arrow key to pick a goal.' : 'Switch to the board to use these keys.'}</p>
      {!board && store.state.activeView === 'inbox' ? <p className="keyboard-guide__context">In Inbox, Enter opens a goal.</p> : null}
      {commandFilter.text ? <p className="keyboard-guide__context">Clear the filter to create a new goal.</p> : null}
      <div className="keyboard-guide__grid"><div>{group('Navigate')}{group('History')}</div><div>{group('Goals')}</div></div>
      <p className="keyboard-guide__editing"><strong>Editing a title?</strong> <Keys values={['Enter']} /> saves. <Keys values={['Esc']} /> cancels.<br />In notes, Enter starts a new line.</p>
      <footer className="keyboard-guide__foot"><span><Keys values={['?']} /> opens this guide on the board</span><span><Keys values={['Esc']} /> Close</span></footer>
    </dialog>
  </>
})
