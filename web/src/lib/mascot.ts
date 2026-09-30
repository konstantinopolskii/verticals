// The mascot's life at rest (docs/design-handoff S1.P1): plays when you leave it be, pong when nobody is there, its line
// watching the goal you point at, a jump for a goal just made and a blink for one moved. Every number is a hidden
// setting (R.073). Nothing here runs with reduced motion (S0.P1.028).
import { computed, onBeforeUnmount, onMounted, reactive, watch, type Ref } from 'vue'
import { store } from '../store'
import { circle, circleNews, circleState } from './circle'
import { curve, reducedMotion } from './motion'
import { defineKnobs, knob } from './tuning'

const ms = (key: string, label: string, value: number, max: number) =>
  ({ key, label, value, min: 0, max, step: 50, unit: 'ms' })
defineKnobs('The circle', [
  ms('circle.firstPlayMs', 'First play, after you stop acting', 20000, 120000),
  ms('circle.playEveryMinMs', 'Next play, at the soonest', 40000, 180000),
  ms('circle.playEveryMaxMs', 'Next play, at the latest', 90000, 300000),
  ms('circle.pongAfterMs', 'Pong, after no input at all', 15000, 300000),
  ms('circle.lookRestMs', 'Look at a goal after resting on it', 100, 1000),
  ms('circle.lookBackMs', 'Look ahead again after leaving the goals', 1200, 5000),
  ms('circle.newLookMs', 'Look at a new goal for', 1500, 5000),
  { key: 'circle.lookFarPx', label: 'Look: how far the line moves', value: 13, min: 0, max: 30, step: 1, unit: 'px' },
  { key: 'circle.lookTilt', label: 'Look: share of the goal\'s angle', value: 0.35, min: 0, max: 1, step: 0.05 },
  { key: 'circle.lookMaxDeg', label: 'Look: most lean', value: 20, min: 0, max: 45, step: 1, unit: '°' },
  { key: 'circle.jumpPx', label: 'Jump height', value: 14, min: 0, max: 40, step: 1, unit: 'px' },
  { key: 'circle.breathScale', label: 'Breath', value: 1.045, min: 1, max: 1.2, step: 0.005 },
  { key: 'circle.lookAroundPx', label: 'Looking around', value: 9, min: 0, max: 30, step: 1, unit: 'px' },
  { key: 'circle.tiltDeg', label: 'Tilt', value: 18, min: 0, max: 60, step: 1, unit: '°' },
])

export type Pose = { x: number; y: number; r: number; sx: number; sy: number }
const STILL: Pose = { x: 0, y: 0, r: 0, sx: 1, sy: 1 }
export const transformOf = (p: Pose) => `translate(${p.x}px, ${p.y}px) rotate(${p.r}deg) scale(${p.sx}, ${p.sy})`

/** One element's transform, moved from wherever it is (a running move included) to a pose, and kept there. */
export class Mover {
  pose: Pose = { ...STILL }
  private anim: Animation | null = null
  constructor(private el: HTMLElement) {}
  set(to: Partial<Pose>): void {
    this.anim?.cancel()
    this.anim = null
    this.pose = { ...this.pose, ...to }
    this.el.style.transform = transformOf(this.pose)
  }
  async to(to: Partial<Pose>, duration: number, easing: string, delay = 0): Promise<boolean> {
    const from = getComputedStyle(this.el).transform
    const target = { ...this.pose, ...to }
    this.anim?.cancel()
    const anim = this.el.animate(
      [{ transform: from === 'none' ? transformOf(this.pose) : from }, { transform: transformOf(target) }],
      { duration: Math.max(1, duration), easing, delay, fill: 'forwards' },
    )
    this.anim = anim
    this.pose = target
    this.el.style.transform = transformOf(target)
    try { await anim.finished } catch { return false }
    if (this.anim === anim) { anim.cancel(); this.anim = null }
    return true
  }
  stop(): void { this.anim?.cancel(); this.anim = null; this.el.style.transform = transformOf(this.pose) }
}

/** Pong's second line and ball show while this is on; the field widens into an oval for it. */
export const mascot = reactive({ pong: false })

const wait = (duration: number, signal: { stopped: boolean }) =>
  new Promise<boolean>((resolve) => setTimeout(() => resolve(!signal.stopped), duration))
const between = (a: number, b: number) => a + Math.random() * Math.max(0, b - a)

type Parts = {
  line: Ref<HTMLElement | null>
  surface: Ref<HTMLElement | null>
  body: Ref<HTMLElement | null>
  center: () => { x: number; y: number } | null
}

export function useMascot(parts: Parts, mayLook: () => boolean) {
  let line: Mover | null = null
  let surface: Mover | null = null
  let body: Mover | null = null
  let play: { stopped: boolean } | null = null
  let lastAct = performance.now()
  let lastInput = performance.now()
  let nextPlay = knob('circle.firstPlayMs')
  let lookTimer: ReturnType<typeof setTimeout> | null = null
  let lookingAt: string | null = null
  let ticker: ReturnType<typeof setInterval> | null = null

  const resting = computed(() => circleState.value === 'rest' && !store.state.drag.id && !store.state.drag.pending
    && !store.state.openGoalId && !circle.moving)
  const inFront = () => document.visibilityState === 'visible' && document.hasFocus()

  function stopPlay(): void {
    if (play) play.stopped = true
    play = null
  }
  function stopPong(): void {
    if (!mascot.pong) return
    mascot.pong = false
    line?.set({ x: 0, y: 0 })
  }
  function acted(): void {
    lastAct = lastInput = performance.now()
    nextPlay = knob('circle.firstPlayMs')
    stopPlay()
    stopPong()
  }
  function moved(): void {
    lastInput = performance.now()
    stopPong()
  }

  async function runPlay(): Promise<void> {
    if (!line || !surface) return
    const signal = { stopped: false }
    play = signal
    const e = curve('play')
    const kind = Math.floor(Math.random() * 3)
    if (kind === 0) {
      const far = knob('circle.lookAroundPx')
      if (await line.to({ x: -far }, 420, e) && await wait(450, signal)
        && await line.to({ x: far }, 640, e) && await wait(380, signal)) await line.to({ x: 0 }, 440, e)
    } else if (kind === 1) {
      if (await line.to({ r: knob('circle.tiltDeg') }, 480, e) && await wait(700, signal)) await line.to({ r: 0 }, 520, e)
    } else {
      const b = curve('breath'), s = knob('circle.breathScale')
      if (await surface.to({ sx: s, sy: s }, 1300, b)) await surface.to({ sx: 1, sy: 1 }, 1300, b)
    }
    if (play === signal) play = null
  }

  function tick(): void {
    if (!resting.value || !inFront() || reducedMotion()) {
      if (!resting.value) stopPong()
      return
    }
    const now = performance.now()
    if (!mascot.pong && now - lastInput > knob('circle.pongAfterMs')) {
      stopPlay()
      line?.set({ x: 0, y: 0, r: 0 })
      mascot.pong = true
      return
    }
    if (!mascot.pong && !play && !lookingAt && now - lastAct > nextPlay) {
      nextPlay = now - lastAct + between(knob('circle.playEveryMinMs'), knob('circle.playEveryMaxMs'))
      void runPlay()
    }
  }

  function aim(id: string): Partial<Pose> | null {
    const target = document.querySelector(`[data-goal-id="${CSS.escape(id)}"] .goal-card__row`)
    const from = parts.center()
    if (!target || !from) return null
    const box = target.getBoundingClientRect()
    if (box.bottom < 0 || box.top > innerHeight || box.width === 0) return null
    const dx = box.left + box.width / 2 - from.x, dy = box.top + box.height / 2 - from.y, d = Math.hypot(dx, dy) || 1
    const far = knob('circle.lookFarPx'), max = knob('circle.lookMaxDeg')
    const deg = (Math.atan2(dx, -dy) * 180) / Math.PI
    return { x: (dx / d) * far, y: (dy / d) * far, r: Math.max(-max, Math.min(max, deg * knob('circle.lookTilt'))) }
  }
  async function lookAt(id: string, duration = 150): Promise<boolean> {
    const pose = aim(id)
    if (!pose || !line) return false
    stopPlay()
    lookingAt = id
    return line.to(pose, duration, curve('large'))
  }
  function lookAhead(duration = 420): void {
    lookingAt = null
    if (line && resting.value && !mascot.pong) void line.to({ x: 0, y: 0, r: 0 }, duration, curve('play'))
  }

  watch(() => store.state.hoverChainId, (id) => {
    if (lookTimer) clearTimeout(lookTimer)
    lookTimer = null
    if (reducedMotion() || !resting.value || !mayLook()) return
    if (id) lookTimer = setTimeout(() => void lookAt(id), knob('circle.lookRestMs'))
    else if (lookingAt) lookTimer = setTimeout(() => lookAhead(), knob('circle.lookBackMs'))
  })

  watch(resting, (now) => {
    if (now) { lookingAt = null; line?.set({ x: 0, y: 0, r: 0, sy: 1 }) }
    else { stopPlay(); stopPong(); if (lookTimer) clearTimeout(lookTimer) }
  })

  watch(() => circleNews.made, async (news) => {
    if (!news || !body || !surface || !line || reducedMotion() || !resting.value) return
    stopPlay()
    const up = knob('circle.jumpPx')
    const look = aim(news.id)
    lookingAt = look ? news.id : null
    await Promise.all([body.to({ y: -up }, 170, curve('large')), look ? line.to(look, 170, curve('large')) : null])
    await body.to({ y: 0 }, 150, curve('fall'))
    await surface.to({ sx: 1.1, sy: 0.9 }, 70, curve('large'))
    await surface.to({ sx: 1, sy: 1 }, 220, curve('large'))
    if (!look) return
    setTimeout(() => { if (lookingAt === news.id) lookAhead(450) }, knob('circle.newLookMs'))
  })

  watch(() => circleNews.moved, async (news) => {
    if (!news || !line || reducedMotion() || !resting.value) return
    await line.to({ sy: 0.12 }, 70, curve('large'))
    await line.to({ sy: 1 }, 90, curve('large'))
    if (await lookAt(news.id)) setTimeout(() => { if (lookingAt === news.id) lookAhead() }, knob('circle.newLookMs'))
  })

  function onScroll(): void {
    if (lookingAt && !aim(lookingAt)) lookAhead(150)
  }

  onMounted(() => {
    line = parts.line.value && new Mover(parts.line.value)
    surface = parts.surface.value && new Mover(parts.surface.value)
    body = parts.body.value && new Mover(parts.body.value)
    for (const type of ['keydown', 'pointerdown', 'wheel']) window.addEventListener(type, acted, { capture: true, passive: true })
    window.addEventListener('pointermove', moved, { capture: true, passive: true })
    window.addEventListener('scroll', onScroll, { capture: true, passive: true })
    ticker = setInterval(tick, 250)
  })
  onBeforeUnmount(() => {
    for (const type of ['keydown', 'pointerdown', 'wheel']) window.removeEventListener(type, acted, { capture: true })
    window.removeEventListener('pointermove', moved, { capture: true })
    window.removeEventListener('scroll', onScroll, { capture: true })
    if (ticker) clearInterval(ticker)
    if (lookTimer) clearTimeout(lookTimer)
    stopPlay()
  })

  return { mover: () => line }
}

/** Goals made or moved on the board you are looking at, for the jump and the blink (S1.P1.041, .071). */
export function watchBoardNews(): () => void {
  type Seen = { place: string; made: boolean; created: number }
  let anchor: string | null = null
  let seen: Map<string, Seen> | null = null
  return watch(() => store.state.board, (board) => {
    if (!board) return
    const next = new Map<string, Seen>()
    const add = (goal: { id: string; period_key: string | null; parent_id: string | null; vertical: string | null;
      created_at: string; updated_at: string }) => {
      const created = Date.parse(goal.created_at)
      next.set(goal.id, {
        place: `${goal.vertical}|${goal.period_key}|${goal.parent_id}`,
        made: Math.abs(Date.parse(goal.updated_at) - created) < 2000,
        created,
      })
    }
    for (const column of board.columns) for (const goal of column.goals) add(goal)
    for (const children of Object.values(board.children ?? {})) for (const goal of children) add(goal)
    const previous = anchor === board.anchor_date ? seen : null
    anchor = board.anchor_date
    seen = next
    if (!previous) return
    let made: [string, number] | null = null
    let moved: string | null = null
    for (const [id, now] of next) {
      const before = previous.get(id)
      if (!before && now.made) { if (!made || now.created > made[1]) made = [id, now.created] }
      else if (before && before.place !== now.place) moved = id
    }
    if (made) circleNews.made = { id: made[0], at: performance.now() }
    else if (moved) circleNews.moved = { id: moved, at: performance.now() }
  })
}
