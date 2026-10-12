<script setup lang="ts">
// The notice (docs/design/board-undo.md): a change that leaves your view is said where the field stands. One black pill,
// 64 px tall, one line at 15/22 in white saying what happened to which goal (the goal's title is cut with “…”, the words
// around it never are) and Undo as a white pill at its right end. It stays six seconds and the field comes back; Esc, or
// a click anywhere else, ends it sooner, and the pointer on it holds the time (`lib/fieldNotice.ts`). It lives in its own
// component so the field (`SearchBar.vue`) is not touched; the field is hidden while the notice is up, by one attribute on
// the page, so the two never stand in the same place.
// A question (⌘Z asking whose change it meant, docs/design/agent-answer-undo.md) is the same pill with "Take back" and the
// candidates as pills. When that is wider than the window, "Take back" keeps a row of its own and the pills go under it, side
// by side while they fit and one under the other when they do not. A pill is never wider than the notice: it tries one line, with
// its goal's title cut with “…”; when that would leave the title fewer than 12 letters it takes a second line and the title gets
// that room, and past two lines the title is cut again. The words around the title are never cut.
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { editsText } from '../lib/boardHistory'
import { dismiss, hold, notice, release, type NoticeChoice, type Segment } from '../lib/fieldNotice'
import { cutTitle, glyphs } from '../lib/titleCut'
import { store } from '../store'
import './fieldNotice.css'

const pill = ref<HTMLElement | null>(null)
const line = ref<HTMLElement | null>(null)
/** The pills of a question (⌘Z asking whose change it meant), when there is one. */
const choiceEls = ref<HTMLElement[]>([])
/** The titles as the notice shows them, by the place of their segment (`L:2` in the line, `1:2` in the second pill): whole, or cut
 *  to fit. */
const cuts = ref<Record<string, string>>({})
/** A question that does not fit on one row: its words on a row of their own, the pills under them. */
const stacked = ref(false)
/** The pills (by their place) that take a second line: with their title cut to fit one line it would be left too short to tell
 *  which goal it is, or their words alone are wider than the notice. */
const wrapped = ref<Record<string, boolean>>({})
let fitting = 0

/** Two lines at 15/22 with 9 px above and below: as tall as a pill whose words go on to a second line may be. */
const TWO_LINES = 62
/** A title cut on one line to fewer letters than this names no goal anyone can tell: its pill takes a second line instead. */
const MIN_LETTERS = 12

const overflows = (el: HTMLElement): boolean => el.scrollWidth > el.clientWidth
const runsOver = (el: HTMLElement): boolean => (wrapped.value[el.dataset.choice ?? ''] ? el.scrollHeight > TWO_LINES : overflows(el))

interface Title { key: string; text: string; length: number }

/** The titles whole if they do not run over, else the longest start of them that does not, found by halving. Two titles (“into”,
 *  “out of”) give up the same share of their length. `false`: another notice has come, or this one has gone. */
async function shorten(mine: number, titles: Title[], spills: () => boolean): Promise<boolean> {
  const longest = Math.max(0, ...titles.map((title) => title.length))
  const cutTo = (keep: number): Record<string, string> =>
    Object.fromEntries(titles.map((title) => [title.key, cutTitle(title.text, Math.round((title.length * keep) / longest))]))
  cuts.value = { ...cuts.value, ...cutTo(longest) }
  await nextTick()
  if (mine !== fitting || !line.value) return false
  if (!spills()) return true
  let fits = 0
  let over = longest
  while (fits < over - 1) {
    const middle = Math.ceil((fits + over) / 2)
    cuts.value = { ...cuts.value, ...cutTo(middle) }
    await nextTick()
    if (mine !== fitting || !line.value) return false
    if (spills()) over = middle
    else fits = middle
  }
  cuts.value = { ...cuts.value, ...cutTo(fits) }
  await nextTick()
  return mine === fitting && !!line.value
}

/** Whether a title has been cut to fewer letters than `MIN_LETTERS`, or than all it has when it has fewer than that. */
const cutTooShort = (titles: Title[]): boolean =>
  titles.some((title) => {
    const shown = cuts.value[title.key]
    return shown !== undefined && shown !== title.text && glyphs(shown).length - 1 < Math.min(MIN_LETTERS, title.length)
  })

/* A title that does not fit is cut in the text, so the “…” stands right after its last letter, with no space before it and
   the quote right after it (the browser's ellipsis cuts at a pixel and leaves gaps). The pill is as wide as its words up to
   its largest, so a line that overflows is one that is cut short: the longest start of the title that does not overflow is
   found by halving. A question goes onto more rows before any title is cut, and then each pill is cut to its own row. Everything
   runs before the next frame, so the whole title is never drawn. */
async function fit(): Promise<void> {
  const mine = (fitting += 1)
  cuts.value = {}
  stacked.value = false
  wrapped.value = {}
  await nextTick()
  const spills = (): boolean => !!line.value && (overflows(line.value) || choiceEls.value.some(runsOver))
  if (mine !== fitting || !line.value || !spills()) return
  const quotes = (segments: Segment[], where: string): Title[] =>
    segments.flatMap((part, at) => ('quote' in part ? [{ key: `${where}:${at}`, text: part.quote, length: glyphs(part.quote).length }] : []))
  if (!notice.choices.length) {
    await shorten(mine, quotes(notice.segments, 'L'), spills)
    return
  }
  stacked.value = true
  await nextTick()
  for (const [at, choice] of notice.choices.entries()) {
    const own = (): HTMLElement | undefined => choiceEls.value.find((el) => el.dataset.choice === String(at))
    const runsOverAlone = (): boolean => !!own() && runsOver(own()!)
    if (mine !== fitting) return
    if (!runsOverAlone()) continue
    const titles = quotes(choice.label, String(at))
    if (!(await shorten(mine, titles, runsOverAlone))) return
    // One line has cut the title too short to tell the goal, or the words alone are wider than the notice: the pill takes a second
    // line, and the title takes the room that gives.
    if (own() && (overflows(own()!) || cutTooShort(titles))) {
      wrapped.value = { ...wrapped.value, [String(at)]: true }
      await nextTick()
      if (!(await shorten(mine, titles, runsOverAlone))) return
    }
  }
}

// `sync`: the field is shown again in the same task as the key that asks for it, or it could not take the focus (see below).
watch(() => notice.open, (open) => document.documentElement.toggleAttribute('data-field-notice', open), { immediate: true, flush: 'sync' })
watch(() => notice.seq, () => { stacked.value = false; wrapped.value = {}; cuts.value = {} }, { flush: 'pre' })
watch(() => notice.seq, () => void fit(), { flush: 'post' })
const refit = (): void => { if (notice.open) void fit() }

function act(): void {
  const action = notice.action
  dismiss()
  action?.run()
}

/** A pick of the question: the question goes, and what was picked is taken back. */
function pick(choice: NoticeChoice): void {
  dismiss()
  choice.run()
}

/* A key that asks for the field (a letter, which is its first one, or ⌘K, `SearchBar.vue`) puts the field back first: it is
   hidden while the notice stands, and a hidden field cannot take the focus. */
const asksForField = (event: KeyboardEvent): boolean => {
  const command = event.metaKey || event.ctrlKey
  if (event.altKey) return false
  return command ? event.key.toLowerCase() === 'k' : event.key.length === 1 && event.key !== ' '
}

/* Esc ends it, ahead of the field (which would clear an answer behind it) and of the windows (the smaller thing goes
   first). Inside a text field, and while a goal is in the hand, Esc is theirs. */
function onKeyDown(event: KeyboardEvent): void {
  if (!notice.open || event.defaultPrevented || editsText(event.target)) return
  if (asksForField(event) && !store.state.drag.id && !store.state.drag.pending) dismiss()
  if (event.key !== 'Escape' || store.state.drag.id || store.state.drag.pending) return
  event.preventDefault()
  event.stopImmediatePropagation()
  dismiss()
}
/* A press anywhere but on the notice ends it; the press itself goes on to what it was aimed at. */
function onPointerDown(event: PointerEvent): void {
  if (notice.open && !(event.target instanceof Node && pill.value?.contains(event.target))) dismiss()
}

onMounted(() => {
  window.addEventListener('keydown', onKeyDown, true)
  window.addEventListener('pointerdown', onPointerDown, true)
  window.addEventListener('resize', refit)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeyDown, true)
  window.removeEventListener('pointerdown', onPointerDown, true)
  window.removeEventListener('resize', refit)
  document.documentElement.removeAttribute('data-field-notice')
})
</script>

<template>
  <Transition name="field-notice">
    <div
      v-if="notice.open"
      ref="pill"
      class="field-notice"
      :class="{
        'field-notice--bare': !notice.action && !notice.choices.length,
        'field-notice--question': notice.choices.length > 0,
        'field-notice--stacked': stacked && notice.choices.length > 0,
      }"
      data-role="field-notice"
      role="status"
      aria-live="polite"
      @pointerenter="hold"
      @pointerleave="release"
    >
      <p ref="line" class="field-notice__line" data-role="field-notice-line">
        <template v-for="(part, at) in notice.segments" :key="at">
          <span v-if="'text' in part" class="field-notice__text">{{ part.text }}</span>
          <span v-else class="field-notice__quote"><i>“</i><span class="field-notice__title">{{ cuts[`L:${at}`] ?? part.quote }}</span><i>”</i></span>
        </template>
      </p>
      <button
        v-for="(choice, at) in notice.choices"
        :key="at"
        ref="choiceEls"
        type="button"
        class="field-notice__action field-notice__choice"
        :class="{ 'field-notice__choice--wrapped': wrapped[at] }"
        data-role="field-notice-choice"
        :data-choice="at"
        @click="pick(choice)"
      >
        <template v-for="(part, place) in choice.label" :key="place">
          <span v-if="'text' in part" class="field-notice__text">{{ part.text }}</span>
          <span v-else class="field-notice__quote"><i>“</i><span class="field-notice__title">{{ cuts[`${at}:${place}`] ?? part.quote }}</span><i>”</i></span>
        </template>
      </button>
      <button v-if="notice.action" type="button" class="field-notice__action" data-role="field-notice-action" @click="act">
        {{ notice.action.label }}
      </button>
    </div>
  </Transition>
</template>
