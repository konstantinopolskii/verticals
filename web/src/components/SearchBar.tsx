/* The circle and the field at the bottom of every screen: one black shape that is the
   mascot at rest, the field you type into, the agent's step, answer and ask, with the tags and what waits while a goal
   moves above it. */
import type { MouseEvent, PointerEvent as ReactPointerEvent, ReactNode } from 'react'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, type Ref } from '../reactivity'
import { store } from '../store'
import { commandFilter, filterText } from '../lib/commandFilter'
import { fieldUndo } from '../lib/fieldUndo'
import { circle, circleCaption, circleState, circleWords, inboxWriting } from '../lib/circle'
import { answerChips, answerSize, answerText, choices, undoable } from '../lib/circleAnswer'
import { carry } from '../lib/inboxCarry'
import { agentChat, openAsk, stop } from '../lib/agentChat'
import { windows } from '../lib/windows'
import { viewport } from '../lib/viewport'
import { mascot, watchBoardNews } from '../lib/mascot'
import { followWords } from '../lib/finding'
import { curve, reducedMotion } from '../lib/motion'
import { launch } from '../lib/chatFlight'
import { defineKnobs, knob } from '../lib/tuning'
import { fontEpoch, fontOf, widthOf } from '../lib/fitName'
import { CIRCLE, fieldHeight, fieldWidth, LINE, PAD_LEFT, PAD_Y } from '../lib/fieldSize'
import { fieldMascot, lineModeOf } from '../lib/fieldMascot'
import { fieldKeys } from '../lib/fieldKeys'
import { searchWords } from '../lib/urlState'
import { dots } from '../lib/spansDrag'
import { pictures, reporting, stackRoom, watchPictureInput } from '../lib/reportPictures'
import { brush, type Brush } from '../lib/brush'
import { AgentStep } from './AgentStep'
import { CircleGame } from './CircleGame'
import { CircleTags } from './CircleTags'
import { FieldAnswer } from './FieldAnswer'
import { FieldInput } from './FieldInput'
import { MascotLine } from './MascotLine'
import { MovingStack } from './MovingStack'
import { bindRef, cx, fallthrough, sx } from '../bind'
import { tracked } from '../tracked'
import { exposeTo, listen, useSetup } from '../setup'
import './circleField.css'

export interface SearchBarApi {
  focusField(): void
}

interface Props {
  agentAvailable: boolean
  onSubmit?: (text: string) => void
  expose?: Ref<SearchBarApi | null>
  /** Drawn first in the space above the field. */
  above?: ReactNode
  /** The agent's tag among the tags above the field. */
  agentTag?: ReactNode
}

/** A custom property on <html> that follows `value`, for what stands on the field. Inside useSetup. */
function rootVar(name: string, value: () => string): void {
  watch(value, (v) => document.documentElement.style.setProperty(name, v), { immediate: true })
}

export const SearchBar = tracked(function SearchBar(raw: Props & Record<string, unknown>) {
  const { agentAvailable, onSubmit, expose, above, agentTag, ...attrs } = raw
  const s = useSetup({ agentAvailable, onSubmit, expose }, (props) => {
    defineKnobs('The field', [
      { key: 'field.maxLines', label: 'Lines before the field scrolls', value: 10, min: 1, max: 20, step: 1 },
    ])

    const body = ref<HTMLElement | null>(null)
    const shape = ref<HTMLElement | null>(null)
    const surface = ref<HTMLElement | null>(null)
    const line = ref<HTMLElement | null>(null)
    const input = ref<HTMLTextAreaElement | null>(null)
    const mirror = ref<HTMLElement | null>(null)
    const pivot = ref<HTMLElement | null>(null)
    const size = answerSize()

    const hand = ref<{ x: number; y: number } | null>(null)
    const onTags = ref(false)
    const caret = ref<{ x: number; y: number }>({ x: 0, y: 0 })
    const selecting = ref(false)
    /* The shape follows the words' flight at its pace: 280 ms when they are sent, 300 ms when the answer goes up. */
    const flying = ref<'sent' | 'reply' | null>(null)
    let flyingTimer: ReturnType<typeof setTimeout> | null = null
    function fly(kind: 'sent' | 'reply'): void {
      flying.value = kind
      if (flyingTimer) clearTimeout(flyingTimer)
      flyingTimer = setTimeout(() => { flying.value = null }, 420)
    }
    const still = ref(true)
    const lines = ref(1)

    const state = circleState
    const text = computed(() => commandFilter.text)
    const maxWidth = computed(() => Math.max(CIRCLE, Math.min(720, viewport.width - 32)))

    /* Under a pointer that can hover, the resting circle only widens: 116 px, its line 5 × 46 px and upright, the buttons
       above it 38 px (circleField.css). It opens on a click, a key or ⌘K, never on the pointer (docs/design/field-hover.md). */
    const hoverQuery = typeof matchMedia === 'function' ? matchMedia('(hover: hover) and (pointer: fine)') : null
    const canHover = ref(hoverQuery?.matches ?? false)
    function onCanHover(event: MediaQueryListEvent): void { canHover.value = event.matches }
    const hovered = computed(() => circle.pointed && canHover.value && state.value === 'rest')

    /* Words are measured in the field's face, again once a face has loaded (lib/fitName.ts), or a pasted line wraps out of
       sight. */
    function textWidth(value: string): number {
      void fontEpoch.value
      if (!input.value) return 0
      const font = fontOf(input.value)
      return Math.max(0, ...value.split('\n').map((part) => widthOf(part, font)))
    }

    const stopping = computed(() => state.value === 'working' && circle.pointed)
    /* With an ask waiting in the open conversation the circle only waits (no turning line, no step). The step is a
       conversation's: while a report is made from pictures the line turns with none (docs/design/bug-reports.md). */
    const stepShown = computed(() => state.value === 'working' && agentChat.running && !openAsk.value)
    /* Holding a goal over the spans, the field is a pill with the mascot; let go over it, it widens to hold what stands above
       it (S5.P3.002, .007, .039). Let go anywhere else, it stays the pill while the goal lands and the board comes back. */
    const holding = computed(() => carry.over
      // In the Inbox the card waiting above the field, carried out again, is held the same way (docs/design/inbox-carry-stack.md).
      || (state.value === 'moving' && (store.state.drag.id !== null || dots.landing || carry.item !== null)))
    const wide = computed(() => state.value === 'open' || state.value === 'typing' || state.value === 'answer'
      || (state.value === 'moving' && !holding.value))
    const tagsShown = computed(() => hovered.value || (circle.pointed && wide.value) || circle.focused || agentChat.open)

    /* Pictures waiting above the field widen it to hold them: the stack, and what stands at its left end (4 px, or the tags
       and 8) and keeps the stack's room as CSS reads it (FieldPictures). It is as wide as the stack needs and the open field
       was, at once (docs/design/bug-reports.md). */
    const tagsShift = ref(0)
    const picturesRoom = computed(() => (reporting.value ? stackRoom(pictures.list) + Math.max(8, 4 + tagsShift.value) : 0))
    const width = computed(() => Math.min(maxWidth.value, Math.max(picturesRoom.value, fieldWidth({
      state: state.value,
      maxWidth: maxWidth.value,
      caption: textWidth(circleCaption.value),
      typed: state.value === 'typing' ? textWidth(text.value) : 0,
      carryOver: carry.over,
      holding: holding.value,
      chips: answerChips.value.length,
      answerWidth: size.answerWidth.value,
      leadLines: size.leadLines.value,
      undoable: undoable.value,
      stepShown: stepShown.value,
      stopping: stopping.value,
      tagsShown: tagsShown.value,
      game: !!mascot.game,
    }))))
    const shownLines = computed(() => Math.min(lines.value, knob('field.maxLines')))
    const height = computed(() => fieldHeight({
      state: state.value,
      lines: shownLines.value,
      chips: answerChips.value.length,
      chipsHeight: size.chipsHeight.value,
      words: !!answerText.value,
      answerLines: size.answerLines.value,
      leadLines: size.leadLines.value,
      ask: circleWords.value?.kind === 'ask',
      choices: choices.value.length > 0,
      undoable: undoable.value,
    }))
    /* The turning line stays 42 px from the left end, the circle's centre, while the circle is a pill: the pivot moves there
       and follows the shape's own timing (circleField.css), so the line holds its place as the black widens and narrows. */
    const stepShift = computed(() => (stepShown.value ? CIRCLE / 2 - width.value / 2 : 0))

    const lineMode = computed(() => lineModeOf({
      state: state.value,
      carryOver: carry.over,
      hovered: hovered.value,
      wide: wide.value,
      inboxWriting: inboxWriting.value,
      focused: circle.focused,
      selecting: selecting.value,
      hand: hand.value,
      onTags: onTags.value,
    }))
    fieldMascot({ line, surface, body, shape }, () => !wide.value, { mode: lineMode, hand, caret, size: [width, height] })

    const sendShown = computed(() => !!text.value)
    const sendLabel = computed(() => {
      if (reporting.value) return 'Make the report'
      return inboxWriting.value ? 'Write it down' : 'Send to the agent'
    })
    const pivotTurning = computed(() => state.value === 'working' && !openAsk.value)
    const pivotStopping = computed(() => stopping.value && !stepShown.value)
    const lineBlinking = computed(() => lineMode.value === 'caret' && circle.focused && still.value)

    function measure(): void {
      const el = input.value
      const copy = mirror.value
      if (!el || !copy) return
      const set = el.style.height
      el.style.height = '0px'
      lines.value = Math.max(1, Math.round(el.scrollHeight / LINE))
      el.style.height = set
      const at = el.selectionStart ?? el.value.length
      selecting.value = el.selectionStart !== el.selectionEnd
      copy.textContent = el.value.slice(0, at)
      const mark = document.createElement('span')
      mark.textContent = '​'
      copy.appendChild(mark)
      const x = el.value ? mark.offsetLeft + 2 : -4
      const y = mark.offsetTop - el.scrollTop
      caret.value = { x: PAD_LEFT + x + 1.5 - width.value / 2, y: PAD_Y + y + LINE / 2 - height.value / 2 }
    }
    let stillTimer: ReturnType<typeof setTimeout> | null = null
    function moved(): void {
      still.value = false
      if (stillTimer) clearTimeout(stillTimer)
      stillTimer = setTimeout(() => { still.value = true }, 500)
      void nextTick(measure)
    }
    watch([text, width, height], () => void nextTick(measure))

    /* The conversation measures itself against the field (S2.P1.009), and moves up when the tags come in (S2.P2.013). */
    rootVar('--vt-field-height', () => `${height.value}px`)
    rootVar('--vt-tags-lift', () => (tagsShown.value ? '44px' : '0px'))
    rootVar('--moving-field-width', () => `${width.value}px`)
    /* Pointed at in the moving mode, the tags take the stack's left end and the stack moves right by their width and 8 px
       (S5.P3.010, .012). */
    watch(tagsShown, async (shown) => {
      await nextTick()
      const tags = shown ? document.querySelector<HTMLElement>('.circle-tags')?.offsetWidth ?? 0 : 0
      tagsShift.value = tags ? tags + 8 : 0
      document.documentElement.style.setProperty('--moving-tags-shift', `${tagsShift.value}px`)
    }, { immediate: true })

    /* While the agent works the line turns; when it answers it ends upright (S2.P3.003). */
    watch(() => state.value === 'working', (working, was) => {
      const el = pivot.value
      if (!el || working || !was) return
      const from = getComputedStyle(el).transform
      if (from && from !== 'none') el.animate([{ transform: from }, { transform: 'none' }], { duration: 165, easing: curve('large') })
    })

    /* The answer goes back into the circle and the conversation keeps it: Esc does it, and so does brushing it away with a
       sideways swipe or a drag down (lib/brush.ts; docs/design/agent-fixes.md, fix 8). */
    function sendBack(): void {
      agentChat.answer = null
    }
    /* The answer goes up into the conversation as its last balloon, and the field takes the caret (S2.P4.003). */
    function reply(): void {
      const words = shape.value?.querySelector('.circle-field__answer-words')?.getBoundingClientRect()
      if (words) launch('reply', words.left, words.top)
      // A press first, then the answer goes up as the black shrinks into the open field (S2.P4.015, .016).
      if (!reducedMotion()) {
        shape.value?.animate([{ transform: 'scale(1)' }, { transform: 'scale(.98)' }, { transform: 'scale(1)' }],
          { duration: 90, easing: curve('large') })
      }
      fly('reply')
      agentChat.answer = null
      agentChat.open = true
      agentChat.engaged = true
      focusField()
    }

    /* ⌘Z in the field is the field's own, a run of typing at a time (`lib/fieldUndo.ts`): the browser's would take a letter. */
    const words = fieldUndo({
      get: () => commandFilter.text,
      set: (text) => {
        commandFilter.text = text
        void nextTick(() => {
          input.value?.setSelectionRange(text.length, text.length)
          moved()
        })
      },
    })
    watch(() => commandFilter.text, (now) => words.changed(now))
    function onInput(event: Event): void {
      const value = (event.target as HTMLTextAreaElement).value
      words.typing(commandFilter.text, (event as InputEvent).inputType ?? '')
      commandFilter.text = value
      words.typed(value)
      moved()
    }
    // Typing, or a click on the field, brings the conversation back; over a window, always (S2.P1.011, .018).
    function engage(): void {
      if (windows.list.length && agentChat.available) agentChat.engaged = true
      // In the Inbox the field writes: an earlier conversation stays where it is until you ask (lib/inbox.ts).
      if (agentChat.engaged && !agentChat.open && (store.state.activeView !== 'inbox' || windows.list.length)) agentChat.open = true
    }
    function focusField(): void {
      const el = input.value
      if (!el) return
      engage()
      el.focus({ preventScroll: true })
      const end = el.value.length
      el.setSelectionRange(end, end)
      moved()
    }
    function clear(): void {
      commandFilter.text = ''
      moved()
    }
    function send(): void {
      const words = commandFilter.text.trim()
      if (!words) return
      // In the Inbox they become the first card in Today, and with pictures above the field they are the report's: no
      // balloon takes them up (lib/inbox.ts, lib/report.ts).
      if (inboxWriting.value || reporting.value) {
        props.onSubmit?.(words)
        return
      }
      // Your words rise from where they stand into your balloon, and the field is the circle again (S2.P3.019).
      const box = input.value?.getBoundingClientRect()
      if (box) launch('sent', box.left, box.top + (LINE - 22) / 2)
      fly('sent')
      props.onSubmit?.(words)
    }
    const keys = fieldKeys({ input, words, send, clear, moved, focus: focusField, reply, sendBack })
    // Native listeners on the field: `inputType` and the real `beforeinput`, `select` and a keydown whose stopPropagation
    // stops at the field.
    listen(input, 'beforeinput', (event) => words.history(event))
    listen(input, 'input', onInput)
    listen(input, 'keydown', keys.onKeyDown)
    listen(input, 'select', moved)

    function fromCentre(event: ReactPointerEvent): { x: number; y: number } | null {
      const box = shape.value?.getBoundingClientRect()
      if (!box) return null
      const half = Math.max(0, width.value / 2 - 20)
      const clamp = (v: number, m: number) => Math.max(-m, Math.min(m, v))
      return { x: clamp(event.clientX - box.left - box.width / 2, half), y: clamp(event.clientY - box.top - box.height / 2, 24) }
    }
    function onShapeMove(event: ReactPointerEvent): void {
      if (event.pointerType === 'touch') return
      circle.pointed = true
      onTags.value = false
      hand.value = fromCentre(event)
    }
    function onTagsEnter(): void { onTags.value = true }
    function onLeave(): void {
      circle.pointed = false
      hand.value = null
      onTags.value = false
    }
    function onShapeClick(event: MouseEvent): void {
      // A click on the words keeps the caret the browser placed there.
      if (event.target === input.value) { engage(); return }
      if (brushing?.swallowed()) return // the end of a drag is no click on the answer
      if (circleWords.value?.kind === 'answer') reply()
      else if (!circleWords.value) focusField()
    }
    // The buttons on the shape act alone: the click does not reach the shape.
    function onSendClick(event: MouseEvent): void {
      event.stopPropagation()
      send()
    }
    function onStopClick(event: MouseEvent): void {
      event.stopPropagation()
      void stop()
    }

    exposeTo(props.expose, { focusField })

    let stopNews: (() => void) | null = null
    let stopFinding: (() => void) | null = null
    let stopPictures: (() => void) | null = null
    let brushing: Brush | null = null
    onMounted(() => {
      if (shape.value) brushing = brush(shape.value, () => state.value === 'answer' && circleWords.value?.kind === 'answer', sendBack)
      const searched = searchWords(location.pathname)
      if (searched) commandFilter.text = searched
      window.addEventListener('keydown', keys.onWindowKeyDown, true)
      hoverQuery?.addEventListener('change', onCanHover)
      stopNews = watchBoardNews()
      stopFinding = followWords(() => filterText.value, () => store.state.board)
      stopPictures = watchPictureInput()
      void document.fonts?.ready.then(() => void nextTick(measure))
    })
    onBeforeUnmount(() => {
      brushing?.stop()
      window.removeEventListener('keydown', keys.onWindowKeyDown, true)
      hoverQuery?.removeEventListener('change', onCanHover)
      stopNews?.()
      stopFinding?.()
      stopPictures?.()
      if (stillTimer) clearTimeout(stillTimer)
      if (flyingTimer) clearTimeout(flyingTimer)
    })

    return {
      body, shape, surface, line, input, mirror, pivot, size, flying, still, lines, state, hovered, stopping, stepShown,
      holding, width, shownLines, height, stepShift, tagsShown, lineMode, sendShown, sendLabel, pivotTurning, pivotStopping,
      lineBlinking, measure, moved, onShapeMove, onTagsEnter, onLeave, onShapeClick, onSendClick, onStopClick,
    }
  })

  const tagsShown = s.tagsShown.value
  const sendShown = s.sendShown.value
  return (
    <div {...fallthrough({
      className: 'circle-field',
      'data-cap': 'search',
      'data-state': s.state.value,
      'data-game': mascot.game ?? undefined,
      'data-pointed': s.hovered.value ? '' : undefined,
      'data-focused': circle.focused ? '' : undefined,
      'data-holding': s.holding.value ? '' : undefined,
      'data-flying': s.flying.value ?? undefined,
      onPointerLeave: s.onLeave,
    }, attrs)}>
      <div className="circle-field__above">
        {above}
        <MovingStack />
        <CircleTags shown={tagsShown} onPointerEnter={s.onTagsEnter} agent={agentTag} />
        <div className={cx('circle-field__bridge', { 'is-shown': tagsShown })} aria-hidden="true"></div>
      </div>
      <div ref={bindRef(s.body)} className="circle-field__body">
        <div
          ref={bindRef(s.shape)}
          className="circle-field__shape"
          style={sx({ width: `${s.width.value}px`, height: `${s.height.value}px` })}
          onPointerEnter={s.onShapeMove}
          onPointerMove={s.onShapeMove}
          onClick={s.onShapeClick}
        >
          <div ref={bindRef(s.surface)} className="circle-field__surface" aria-hidden="true"></div>
          <FieldInput
            input={s.input}
            mirror={s.mirror}
            lines={s.shownLines.value}
            scrolls={s.lines.value > s.shownLines.value}
            onMoved={s.moved}
            onScroll={s.measure}
          />
          <button
            type="button"
            className={cx('circle-field__send', { 'is-shown': sendShown })}
            aria-label={s.sendLabel.value}
            tabIndex={sendShown ? 0 : -1}
            onClick={s.onSendClick}
          >
            <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
              <path d="M12 21.5V3M12 3 5 10M12 3l7 7" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          <FieldAnswer answerMeasure={s.size.answerMeasure} leadMeasure={s.size.leadMeasure} chipsBox={s.size.chipsBox} />
          {s.stopping.value ? (
            <button type="button" className="circle-field__stop" aria-label="Stop the agent" onClick={s.onStopClick}>
              <span aria-hidden="true"></span>
            </button>
          ) : null}
          <AgentStep shown={s.stepShown.value} />
          <MascotLine
            pivot={s.pivot}
            line={s.line}
            turning={s.pivotTurning.value}
            stopping={s.pivotStopping.value}
            blinking={s.lineBlinking.value}
            hidden={s.lineMode.value === 'hidden'}
            shift={s.stepShift.value}
          />
          {mascot.game ? <CircleGame key={mascot.game} game={mascot.game} /> : null}
        </div>
      </div>
    </div>
  )
})
