/* The kit's components the app uses, in the kit's markup and classes. A parent's attributes fall through onto the root
   (bind.ts); a declared event is a prop the component calls. */
import { useLayoutEffect, useRef, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react'
import { cx, fallthrough, valueOf } from '../bind'

type Attrs = Record<string, unknown> & { className?: string; children?: ReactNode }

export function KButton({ primary = false, type = 'button', children, ...attrs }: Attrs & { primary?: boolean; type?: string }) {
  return <button {...fallthrough({ className: 'button t-subtitle' + (primary ? ' button--primary' : ''), type }, attrs)}>{children}</button>
}

export function KCard({ dense = false, children, ...attrs }: Attrs & { dense?: boolean }) {
  return <div {...fallthrough({ className: cx('card', dense ? 'card--dense' : null) }, attrs)}>{children}</div>
}

export function KCardStack({ dense = false, children, ...attrs }: Attrs & { dense?: boolean }) {
  return <div {...fallthrough({ className: cx('card-stack', dense ? 'card-stack--dense' : null) }, attrs)}>{children}</div>
}

export function KChip({ pressed = false, onClick, children, ...attrs }:
  Attrs & { pressed?: boolean; value?: unknown; onClick?: (event: MouseEvent<HTMLButtonElement>) => void }) {
  const own = { className: 'chip', type: 'button', 'aria-pressed': pressed ? 'true' : 'false', onClick: (event: MouseEvent<HTMLButtonElement>) => onClick?.(event) }
  delete attrs.value
  return <button {...fallthrough(own, attrs)}>{children}</button>
}

export function KCheckbox({ label = '', modelValue = false, size = 's', 'onUpdate:modelValue': onUpdate, ...attrs }:
  Attrs & { label?: string; modelValue?: boolean; size?: string; 'onUpdate:modelValue'?: (value: boolean) => void }) {
  // `checked` is the element's property, set when the value changes: a click the parent leaves unanswered stays as the
  // hand left it.
  const input = useRef<HTMLInputElement | null>(null)
  useLayoutEffect(() => {
    if (input.current) input.current.checked = modelValue
  }, [modelValue])
  // The box's own `change`, as the kit's `@change`: after the click, not inside it as React's onChange.
  const update = useRef(onUpdate)
  update.current = onUpdate
  useLayoutEffect(() => {
    const el = input.current
    if (!el) return
    const onChange = () => update.current?.(el.checked)
    el.addEventListener('change', onChange)
    return () => el.removeEventListener('change', onChange)
  }, [])
  return (
    <label {...fallthrough({ className: cx('checkbox', `checkbox--size-${size}`) }, attrs)}>
      <input ref={input} className="checkbox__input" type="checkbox" />
      <span className="checkbox__box"></span>
      {label ? <span className="t-caption">{label}</span> : null}
    </label>
  )
}

export function KInlineAdd({ placeholder = 'Add…', onAdd, ...attrs }: Attrs & { placeholder?: string; onAdd?: (title: string) => void }) {
  function onKeyDown(event: KeyboardEvent<HTMLInputElement>): void {
    if (event.key !== 'Enter') return
    const el = event.currentTarget
    const title = el.value.trim()
    if (!title) return
    onAdd?.(title)
    el.value = ''
  }
  return <input {...fallthrough({ className: 'inline-add', type: 'text', placeholder, onKeyDown }, attrs)} />
}

export function KField({ modelValue = '', placeholder = '', type = 'text', textarea = false, 'onUpdate:modelValue': onUpdate, ...attrs }:
  Attrs & { modelValue?: string; placeholder?: string; type?: string; textarea?: boolean; 'onUpdate:modelValue'?: (value: string) => void }) {
  const field = {
    className: 't-caption field__input',
    placeholder: placeholder || undefined,
    ...valueOf(modelValue, (event) => onUpdate?.(event.currentTarget.value)),
  }
  return (
    <label {...fallthrough({ className: 'field' }, attrs)}>
      {textarea ? <textarea {...field} /> : <input {...field} type={type} />}
    </label>
  )
}

export function KCommentNew({ title = 'Add a comment', placeholder = 'Type a comment', modelValue = '', commitLabel = 'Commit',
  'onUpdate:modelValue': onUpdate, onCommit, ...attrs }: Attrs & {
  title?: string; placeholder?: string; modelValue?: string; commitLabel?: string
  'onUpdate:modelValue'?: (value: string) => void; onCommit?: (value: string) => void
}) {
  return (
    <div {...fallthrough({ className: 'card card--shout comment-new' }, attrs)}>
      <div className="card__heading"><h3 className="t-title">{title}</h3></div>
      <KField textarea placeholder={placeholder} modelValue={modelValue} onUpdate:modelValue={(value: string) => onUpdate?.(value)} />
      <button className="button button--primary t-subtitle" type="button" onClick={() => onCommit?.(modelValue)}>{commitLabel}</button>
    </div>
  )
}

export interface KCommentMessage {
  id: string
  body: string
  role?: string
}

export function KCommentThread({ title, state = 'minimized', archived = false, messages, ...attrs }: Attrs & {
  title: string; state?: string; archived?: boolean; messages: KCommentMessage[]
}) {
  const own = { className: 'card card--interactive comment-thread', 'data-state': state, 'data-archived': archived ? 'true' : undefined }
  return (
    <div {...fallthrough(own, attrs)}>
      <div className="card__heading"><h3 className="t-title">{title}</h3></div>
      <div className="card__collapsible">
        <div className="card__collapsible-inner">
          {messages.map((msg) => (
            <div key={msg.id} className="comment-msg" data-message-id={msg.id} data-author-role={msg.role === 'agent' ? 'agent' : undefined}>
              <p className="t-caption">{msg.body}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export function KCommentStack({ children, ...attrs }: Attrs) {
  return <div {...fallthrough({ className: 'comment-stack' }, attrs)}>{children}</div>
}
