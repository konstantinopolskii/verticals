/* The windows over the board (lib/windowStack.ts). Under the conversation the centre one steps back and blurs down its
   height. */
import type { WheelEvent as ReactWheelEvent } from 'react'
import { nextTick, ref, watch } from '../reactivity'
import { ProgressiveBlur } from './ProgressiveBlur'
import { GoalWindowBody } from './GoalWindowBody'
import { PageWindowBody } from './PageWindowBody'
import { DocWindowBody } from './DocWindowBody'
import { InstructionsWindowBody } from './InstructionsWindowBody'
import { WindowHead } from './WindowHead'
import { agentChat } from '../lib/agentChat'
import { focusWindow, windows, type VtWindow } from '../lib/windows'
import { placeWindow, popOut, swipeWindows, windowWidth } from '../lib/windowStack'
import { viewport } from '../lib/viewport'
import { goalLight } from '../lib/look'
import { store } from '../store'
import { bindRef, bindRefAt, cx, fallthrough, sx } from '../bind'
import { tracked } from '../tracked'
import { listen, useSetup } from '../setup'
import { TransitionGroup } from '../Transition'
import './windowStack.css'

function lightOf(win: VtWindow) {
  const goal = store.state.goalDetail
  return goalLight(win.kind === 'goal' && goal?.id === win.target ? goal.color : null)
}

export const WindowStack = tracked(function WindowStack(attrs: Record<string, unknown>) {
  const s = useSetup({}, () => {
    const root = ref<HTMLElement | null>(null)
    const frames = ref<Record<string, HTMLElement | null>>({})
    const scrollers = ref<Record<string, HTMLElement | null>>({})

    watch(() => windows.origin, async (origin) => {
      if (!origin) return
      await nextTick()
      const el = frames.value[origin.key]
      windows.origin = null
      if (el) popOut(el, origin.rect)
    })

    // Native and on the stack: React's onClick would also hear clicks in the popovers a window's content teleports.
    listen(root, 'click', (event) => {
      const key = (event.target as Element).closest<HTMLElement>('.vt-window')?.dataset.key
      const index = windows.list.findIndex((win) => win.key === key)
      if (index < 0) return
      if (index !== windows.front) {
        event.preventDefault()
        event.stopPropagation()
        focusWindow(index)
        return
      }
      if (!agentChat.open) return
      agentChat.open = false
      const field = document.activeElement
      if (field instanceof HTMLElement && field.closest('[data-cap="search-input"]')) field.blur()
    }, { capture: true })

    return { root, frames, scrollers }
  })

  const width = windowWidth(viewport.width)
  return (
    <div ref={bindRef(s.root)} {...fallthrough({
      className: 'window-stack',
      'data-role': 'window-stack',
      onWheel: (event: ReactWheelEvent) => swipeWindows(event.nativeEvent),
    }, attrs)}>
      <TransitionGroup name="vt-window">
        {windows.list.map((win, index) => {
          const front = index === windows.front
          const at = placeWindow(index - windows.front, viewport.width, agentChat.open)
          const lit = lightOf(win)
          return (
            <section
              key={win.key}
              ref={bindRefAt(s.frames, win.key)}
              className={cx('vt-window vt-shadow', {
                'vt-shadow--lit': !!lit,
                'vt-shadow--side': !front,
                'vt-shadow--back': front && agentChat.open,
                'vt-window--front': front,
                'vt-window--side': !front,
                'vt-window--full': win.kind === 'doc',
              })}
              data-window={win.kind}
              data-key={win.key}
              aria-label={front ? win.title : `${win.title}. Bring to the centre`}
              style={sx({
                left: `${at.left}px`,
                width: `${width}px`,
                zIndex: at.z,
                transformOrigin: at.origin,
                '--vt-window-scale': at.scale,
                ...(lit ?? {}),
              })}
            >
              <WindowHead win={win} />
              <div ref={bindRefAt(s.scrollers, win.key)} className="vt-window__body">
                <ProgressiveBlur mode={front ? (agentChat.open ? 'under' : 'none') : 'side'}
                  pale={lit?.['--vt-pale'] ?? '245, 245, 247'} scroller={s.scrollers.value[win.key]}>
                  {win.kind === 'goal' ? (
                    <GoalWindowBody id={win.target} front={front} />
                  ) : win.kind === 'doc' ? (
                    <DocWindowBody id={win.target} part={win.part} />
                  ) : win.kind === 'instructions' ? (
                    <InstructionsWindowBody />
                  ) : (
                    <PageWindowBody url={win.target} />
                  )}
                </ProgressiveBlur>
              </div>
            </section>
          )
        })}
      </TransitionGroup>
    </div>
  )
})
