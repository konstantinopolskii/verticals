<script setup lang="ts">
/* A document's comment on its words (docs/design/doc-comments-inline.md; the owner, round 2 of the agent flows: "show them
   as comments that you can place inline and open right over … simply like in popover"). The card stands in the document,
   under the words it is about from their first letter (over them where the text ends), so it goes by with the text and the
   words and the card are one thing. It is the thread, with a reply field and Resolve, or, on words just selected, the
   field to write the comment in. The comments column on the window's right edge is a goal's alone now (CommentsPanel.vue).

   Where it stands is `lib/cardPlace.ts`'s; opened for words out of view it takes the document to them. Esc, or a press
   anywhere else in the page, closes it, unless words are written in it that would be lost. A comment whose words the text
   no longer holds (an agent rewrote them) stands under the title, with its words quoted. */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { store } from '../store'
import { reducedMotion } from '../lib/motion'
import { HIGHLIGHT_CLASS } from '../lib/commentAnchor'
import { DRAFT_ID } from '../lib/commentAnchoring'
import { placeOverWords } from '../lib/cardPlace'
import type { CommentThread } from '../lib/api'
import './docCommentCard.css'

const props = defineProps<{
  /** The document's own box, which the card is placed in. */
  host: HTMLElement
  /** The text the words are marked in. */
  body: HTMLElement
  /** Counts the times the marks were drawn again, which moves them. */
  paints: number
}>()

/** What the field keeps clear under the text: the white foot it stands on (WindowStack.vue's fade, at rest). */
const FOOT = 168

const comments = store.state.comments
const root = ref<HTMLElement | null>(null)
const field = ref<HTMLTextAreaElement | null>(null)
const draft = ref('')
const placed = ref(false)
const side = ref<'top' | 'bottom'>('bottom')
const unplaced = ref(false)

const composing = computed(() => comments.cardId === null && comments.pendingAnchor !== null)
const thread = computed<CommentThread | null>(() => (comments.cardId ? comments.threads.find((t) => t.id === comments.cardId) ?? null : null))
const wordsId = computed(() => (composing.value ? DRAFT_ID : comments.cardId))
const resolved = computed(() => thread.value?.resolved_at != null)
/** Words that were commented and are not in the text any more: quoted in the card. */
const gone = computed(() => !!thread.value?.anchor && unplaced.value)

function marks(id: string): HTMLElement[] {
  return [...props.body.querySelectorAll<HTMLElement>(`mark.${HIGHLIGHT_CLASS}[data-thread-id="${CSS.escape(id)}"]`)]
}
function light(): void {
  for (const mark of props.body.querySelectorAll(`mark.${HIGHLIGHT_CLASS}.is-active`)) mark.classList.remove('is-active')
  if (wordsId.value) for (const mark of marks(wordsId.value)) mark.classList.add('is-active')
}

/** The element the document scrolls in: this box in Documents, the window's body in a window. */
function scrollerOf(box: HTMLElement): HTMLElement {
  for (let el: HTMLElement | null = box; el; el = el.parentElement) {
    const overflow = getComputedStyle(el).overflowY
    if (overflow === 'auto' || overflow === 'scroll') return el
  }
  return document.documentElement
}

/** Stands the card for its words, and (once, as it opens) takes the document to them when they are out of sight. */
function place(scrollToo: boolean): void {
  const card = root.value
  if (!card) return
  light()
  const rects = (wordsId.value ? marks(wordsId.value) : []).flatMap((mark) => [...mark.getClientRects()]).filter((r) => r.width || r.height)
  unplaced.value = rects.length === 0
  let anchor: { x: number; y: number; width: number; height: number }
  if (rects.length) {
    const first = rects[0]!
    const top = Math.min(...rects.map((r) => r.top))
    const bottom = Math.max(...rects.map((r) => r.bottom))
    anchor = { x: first.left, y: top, width: first.width, height: bottom - top }
  } else {
    // A comment on the whole page, or on words no longer in it: under the title.
    const title = props.host.querySelector<HTMLElement>('[data-role="doc-title"], [data-role="doc-title-input"]')
    const r = (title ?? props.body).getBoundingClientRect()
    anchor = { x: r.left, y: r.top, width: r.width, height: title ? r.height : 0 }
  }
  const scroller = scrollerOf(props.host)
  const box = scroller.getBoundingClientRect()
  const top = Math.max(box.top, 0)
  const visible = { x: box.left, y: top, width: box.width, height: Math.min(box.bottom, innerHeight) - top - FOOT }
  const range = { min: -scroller.scrollTop, max: scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop }
  card.style.maxHeight = ''
  const spot = placeOverWords(anchor, { width: card.offsetWidth, height: card.offsetHeight }, visible, range)
  if (spot.height < card.offsetHeight) card.style.maxHeight = `${spot.height}px`
  const home = props.host.getBoundingClientRect()
  card.style.left = `${spot.x - (home.left - props.host.scrollLeft)}px`
  card.style.top = `${spot.y + spot.scroll - (home.top - props.host.scrollTop)}px`
  side.value = spot.side
  placed.value = true
  if (scrollToo && spot.scroll) scroller.scrollBy({ top: spot.scroll, behavior: reducedMotion() ? 'auto' : 'smooth' })
}

function grow(): void {
  const el = field.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 120)}px`
}

let sending = false
async function send(): Promise<void> {
  const body = draft.value.trim()
  if (!body || sending) return
  sending = true
  try {
    const ok = composing.value
      ? await store.submitNewThread(body)
      : thread.value ? await store.submitReply(thread.value.id, body) : false
    if (ok) {
      draft.value = ''
      void nextTick(grow)
    }
  } finally {
    sending = false
  }
}
function onFieldKey(event: KeyboardEvent): void {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  void send()
}

async function resolve(): Promise<void> {
  const open = thread.value
  if (open && await store.setThreadResolved(open.id, open.resolved_at === null)) store.closeCard()
}

/* A press elsewhere closes the card, unless it is on marked words (which choose what opens) or words are written in it. */
function onPointerDown(event: PointerEvent): void {
  const target = event.target as Element | null
  if (!target || root.value?.contains(target)) return
  if (target.closest(`mark.${HIGHLIGHT_CLASS}, [data-cap="comment-selection"]`)) return
  if (draft.value.trim()) return
  store.closeCard()
}
function onKey(event: KeyboardEvent): void {
  if (event.key !== 'Escape' || event.isComposing) return
  event.preventDefault()
  event.stopPropagation()
  store.closeCard()
}

let watching: ResizeObserver | null = null
const again = (): void => place(false)
onMounted(() => {
  document.addEventListener('pointerdown', onPointerDown, true)
  window.addEventListener('keydown', onKey, true)
  window.addEventListener('resize', again)
  if (root.value && typeof ResizeObserver !== 'undefined') {
    watching = new ResizeObserver(again)
    watching.observe(root.value)
  }
  void nextTick(() => {
    place(true)
    // Once the card shows: a field in a hidden box takes no focus.
    if (composing.value) void nextTick(() => field.value?.focus({ preventScroll: true }))
  })
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onPointerDown, true)
  window.removeEventListener('keydown', onKey, true)
  window.removeEventListener('resize', again)
  watching?.disconnect()
  for (const mark of props.body.querySelectorAll(`mark.${HIGHLIGHT_CLASS}.is-active`)) mark.classList.remove('is-active')
})

// Another comment opens in this card (the list, or a press on other words), or the list asks again for this one.
watch(wordsId, () => {
  placed.value = false
  draft.value = ''
  void nextTick(() => place(true))
})
watch(() => comments.goToSeq, () => void nextTick(() => place(true)))
// The marks were drawn again (a reply landed, the text changed): the words may have moved.
watch(() => props.paints, () => void nextTick(() => place(false)))
// Its thread went (resolved elsewhere, deleted): nothing to show.
watch(thread, (now, was) => { if (was && !now && !composing.value) store.closeCard() })
</script>

<template>
  <section
    ref="root"
    class="doc-card"
    :class="{ 'is-placed': placed, 'is-above': side === 'top' }"
    data-role="comment-card"
    :data-kind="composing ? 'new' : 'thread'"
    :data-thread-id="thread?.id"
    role="group"
    :aria-label="composing ? 'New comment' : 'Comment'"
  >
    <template v-if="thread">
      <p v-if="gone" class="doc-card__quote is-selectable" data-role="comment-quote">
        &ldquo;{{ thread.anchor!.quote }}&rdquo;
        <span class="doc-card__note">These words are no longer in the text.</span>
      </p>
      <div class="doc-card__thread">
        <div
          v-for="(message, i) in thread.messages"
          :key="message.id"
          class="doc-card__msg"
          :class="{ 'doc-card__msg--first': i === 0 && !gone }"
          data-role="comment-message"
          :data-author="message.author"
        >
          <span v-if="message.author === 'agent'" class="doc-card__who">Agent</span>
          <p class="doc-card__said is-selectable">{{ message.body }}</p>
        </div>
      </div>
      <button type="button" class="doc-card__resolve" data-role="comment-resolve" @click="resolve">{{ resolved ? 'Unresolve' : 'Resolve' }}</button>
    </template>
    <div class="doc-card__field">
      <textarea
        ref="field"
        v-model="draft"
        rows="1"
        class="doc-card__input"
        data-role="comment-field"
        :placeholder="composing ? 'Write a comment…' : 'Reply…'"
        :aria-label="composing ? 'Write a comment' : 'Reply'"
        spellcheck="false"
        @input="grow"
        @keydown="onFieldKey"
      ></textarea>
      <button
        type="button"
        class="doc-card__send"
        :class="{ 'is-shown': !!draft.trim() }"
        data-role="comment-send"
        :aria-label="composing ? 'Comment' : 'Reply'"
        :tabindex="draft.trim() ? 0 : -1"
        @click="send"
      >
        <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
          <path d="M12 21.5V3M12 3 5 10M12 3l7 7" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
    </div>
  </section>
</template>
