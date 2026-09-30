// One behaviour for every list of messages (docs/design-handoff S2.P5): a balloon with half of it past the top line of
// the column, or past its bottom line, goes out as it passes (fades, blurs, shrinks; at the bottom it also sinks toward
// the circle) and comes back when half of it is inside again. The check is on position, so it works both ways at any
// speed. While the column moves it blurs a little, most at the start. The lines are drawn by the caller and the column
// scrolls past them, so no balloon is ever cut by an edge.
import { onBeforeUnmount, watch, type Ref } from 'vue'
import { reducedMotion } from './motion'
import { defineKnobs, knob } from './tuning'

defineKnobs('Message scroll', [
  { key: 'scroll.exits', label: 'Balloons go out at the ends (1 = on)', value: 1, min: 0, max: 1, step: 1 },
  { key: 'scroll.blurs', label: 'The column blurs while it moves (1 = on)', value: 1, min: 0, max: 1, step: 1 },
  { key: 'scroll.goneScale', label: 'Gone: scale', value: 0.78, min: 0.3, max: 1, step: 0.01 },
  { key: 'scroll.goneBlur', label: 'Gone: blur', value: 6, min: 0, max: 20, step: 0.5, unit: 'px' },
  { key: 'scroll.sinkX', label: 'Gone at the bottom: toward the middle', value: 22, min: 0, max: 80, step: 1, unit: 'px' },
  { key: 'scroll.sinkY', label: 'Gone at the bottom: down', value: 14, min: 0, max: 80, step: 1, unit: 'px' },
  { key: 'scroll.turn', label: 'Gone: turn', value: 2, min: 0, max: 15, step: 0.5, unit: '°' },
  { key: 'scroll.goneMs', label: 'Going out and back', value: 200, min: 0, max: 800, step: 10, unit: 'ms' },
  { key: 'scroll.moveBlur', label: 'Moving: blur', value: 1.6, min: 0, max: 6, step: 0.1, unit: 'px' },
  { key: 'scroll.moveMs', label: 'Moving: sharp again after', value: 600, min: 100, max: 2000, step: 50, unit: 'ms' },
])

type Side = 'in' | 'top' | 'bottom'
export type Lines = () => { top: number; bottom: number }

export function useMessageScroll(column: Ref<HTMLElement | null>, content: Ref<HTMLElement | null>, lines: Lines, items: () => unknown) {
  let frame = 0
  let lastBlur = 0
  /* A column read to its end stays at its end while it grows or the lines move, as a conversation does. */
  let atEnd = true

  function place(): void {
    frame = 0
    const el = column.value
    if (!el || !content.value) return
    const { top: line, bottom: floor } = lines()
    const exits = knob('scroll.exits') === 1
    const origin = el.getBoundingClientRect().top - el.scrollTop
    const third = (floor - line) / 3
    for (const balloon of content.value.querySelectorAll<HTMLElement>('[data-balloon]')) {
      // Layout boxes, not transformed ones: going out must not move the line that decides it.
      const top = origin + balloon.offsetTop
      const bottom = top + balloon.offsetHeight
      const half = balloon.offsetHeight / 2
      const through = balloon.offsetHeight > floor - line && top < line + 2 * third && bottom > line + third
      let side: Side = 'in'
      if (exits && !through) {
        if (line - top > half) side = 'top'
        else if (bottom - floor > half) side = 'bottom'
      }
      if (balloon.dataset.side !== side) balloon.dataset.side = side
    }
  }
  function schedule(): void {
    if (!frame) frame = requestAnimationFrame(place)
  }
  function onResize(): void {
    if (atEnd && column.value) column.value.scrollTop = column.value.scrollHeight
    schedule()
  }
  function onScroll(): void {
    const el = column.value
    if (el) atEnd = el.scrollTop + el.clientHeight >= el.scrollHeight - 2
    schedule()
    const now = performance.now()
    if (knob('scroll.blurs') !== 1 || reducedMotion() || !content.value || now - lastBlur < 120) return
    lastBlur = now
    const blur = knob('scroll.moveBlur')
    content.value.animate(
      [{ filter: 'blur(0)' }, { filter: `blur(${blur}px)`, offset: 0.22 }, { filter: 'blur(0)' }],
      { duration: knob('scroll.moveMs'), easing: 'ease-out' },
    )
  }

  const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(onResize)
  watch([column, content], ([el, inner], [oldEl, oldInner]) => {
    oldEl?.removeEventListener('scroll', onScroll)
    if (oldEl) resize?.unobserve(oldEl)
    if (oldInner) resize?.unobserve(oldInner)
    el?.addEventListener('scroll', onScroll, { passive: true })
    if (el) resize?.observe(el)
    if (inner) resize?.observe(inner)
    schedule()
  }, { flush: 'post' })
  onBeforeUnmount(() => {
    column.value?.removeEventListener('scroll', onScroll)
    resize?.disconnect()
    if (frame) cancelAnimationFrame(frame)
  })
  watch(items, schedule, { flush: 'post' })

  /** The column's latest exchange at its bottom (S2.P1.012). */
  function toEnd(): void {
    atEnd = true
    if (column.value) column.value.scrollTop = column.value.scrollHeight
    schedule()
  }
  return { toEnd, place: schedule }
}

/** The custom properties a balloon's going out reads, from the hidden settings. */
export function scrollLook(): Record<string, string> {
  return {
    '--gone-scale': String(knob('scroll.goneScale')),
    '--gone-blur': `${knob('scroll.goneBlur')}px`,
    '--gone-x': `${knob('scroll.sinkX')}px`,
    '--gone-y': `${knob('scroll.sinkY')}px`,
    '--gone-turn': `${knob('scroll.turn')}deg`,
    '--gone-ms': `${knob('scroll.goneMs')}ms`,
  }
}
