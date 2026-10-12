<script setup lang="ts">
/* Above the field, while a document is in front (docs/design/doc-comments-inline.md; the owner, round 2 of the agent flows:
   "a pill above the black field with amount of comments … the suggested button like Check again or something"): a pill
   with the number of the document's open comments, which opens them all as a list, and beside it Check again, which hands
   the comments and the edits to the agent (lib/checkAgain.ts) and took the place of the "Ready?" the circle used to ask.
   Check again is the one black pill, as the field is; the count is the light one, in the yellow its words are marked with.

   Its own component, apart from the field (SearchBar.vue): it stands where the conversation keeps clear of the field, 12 px
   over its top, and rises with it as the field grows or its tags come in (`--vt-field-height`, `--vt-tags-lift`); it
   is out of the way while the conversation is open, a message is typed or a goal is moved. The count stays while the
   document has any comment, so a resolved one can still be reached: with none open it reads "3 resolved", grey and with no
   dot (the dot is the yellow of marked words, and resolved words are not marked), and its list is the resolved ones. Nothing
   stands here for a document with no comment at all and nothing to hand over.

   A report (docs/design/bug-reports.md) has two more pills in the same row, black as Check again is: Send to developers, a link
   that opens a GitHub issue filled in with the report (⌥ held, an email draft), and Improve it, which asks the agent for a
   design in the report's task. They stand for the report in front, and for the one the field's answer has just made, so the row
   stands without a document too (lib/reportActions.ts). */
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import DocCommentList from './DocCommentList.vue'
import { store } from '../store'
import { agentChat } from '../lib/agentChat'
import { circle } from '../lib/circle'
import { commandFilter } from '../lib/commandFilter'
import { checkAgain, checkShown } from '../lib/checkAgain'
import { docThreads, followFrontDoc, frontDocId, openThreads } from '../lib/docComments'
import { altHeld, improveIt, improveShown, links, reportShown, sendShown } from '../lib/reportActions'
import './docCheck.css'

const count = computed(() => openThreads.value.length)
const resolved = computed(() => docThreads.value.length - count.value)
/** The document has comments, and none of them is open. */
const resolvedOnly = computed(() => count.value === 0 && resolved.value > 0)
const hasThreads = computed(() => docThreads.value.length > 0)
const label = computed(() => (resolvedOnly.value ? `${resolved.value} resolved` : `${count.value} ${count.value === 1 ? 'comment' : 'comments'}`))
const name = computed(() => (resolvedOnly.value ? `${resolved.value} resolved ${resolved.value === 1 ? 'comment' : 'comments'}` : undefined))
const out = computed(() => agentChat.open || !!commandFilter.text || circle.moving)
const docPills = computed(() => !!frontDocId.value && (hasThreads.value || checkShown.value))
const shown = computed(() => !out.value && (docPills.value || reportShown.value))
const listOpen = computed(() => store.state.comments.listOpen)

const stop = followFrontDoc()
onBeforeUnmount(stop)
// With nothing to stand over (the document gone from the front, or no comment left at all) the list goes; with only resolved
// comments left it stays, and shows them.
watch(shown, (now) => { if (!now) store.setCommentList(false) })

function toggle(): void {
  store.setCommentList(!listOpen.value)
}

/* A pill that goes keeps its place while it fades, out of the row, so the one beside it glides to its new place at once. */
function holdPlace(el: Element): void {
  const pill = el as HTMLElement
  const home = pill.offsetParent?.getBoundingClientRect()
  const box = pill.getBoundingClientRect()
  if (!home) return
  pill.style.left = `${box.left - home.left}px`
  pill.style.top = `${box.top - home.top}px`
}

/* The list goes with Esc, or a press anywhere but on it and its pill. Esc is taken before anything under it (a window,
   the field), as a comment's card takes it. */
function onKey(event: KeyboardEvent): void {
  if (event.key !== 'Escape' || !listOpen.value || event.isComposing) return
  event.preventDefault()
  event.stopPropagation()
  store.setCommentList(false)
}
function onPointerDown(event: PointerEvent): void {
  if (!listOpen.value) return
  const target = event.target as Element | null
  if (target?.closest('[data-role="doc-comments-list"], [data-role="doc-comments-count"]')) return
  store.setCommentList(false)
}
onMounted(() => {
  window.addEventListener('keydown', onKey, true)
  document.addEventListener('pointerdown', onPointerDown, true)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey, true)
  document.removeEventListener('pointerdown', onPointerDown, true)
})
</script>

<template>
  <div v-if="shown" class="doc-check" data-role="doc-check">
    <div class="doc-check__row">
      <TransitionGroup name="doc-check-pill" @before-leave="holdPlace">
        <button
          v-if="hasThreads"
          key="count"
          type="button"
          class="doc-check__pill doc-check__count"
          :class="{ 'doc-check__count--resolved': resolvedOnly }"
          data-role="doc-comments-count"
          :aria-label="name"
          :aria-expanded="listOpen"
          @click="toggle"
        ><i v-if="!resolvedOnly" class="doc-check__dot" aria-hidden="true"></i>{{ label }}</button>
        <button
          v-if="checkShown"
          key="check"
          type="button"
          class="doc-check__pill doc-check__again"
          data-role="doc-check-again"
          @click="checkAgain"
        >Check again</button>
        <a
          v-if="sendShown && links"
          key="send"
          class="doc-check__pill doc-check__send"
          data-role="report-send"
          :href="altHeld ? links.mail : links.issue"
          target="_blank"
          rel="noopener noreferrer"
          title="Opens a GitHub issue with this report for you to read and submit. Hold Option for an email draft."
        >{{ altHeld ? 'Send by email' : 'Send to developers' }}</a>
        <button
          v-if="improveShown"
          key="improve"
          type="button"
          class="doc-check__pill doc-check__improve"
          data-role="report-improve"
          @click="improveIt"
        >Improve it</button>
      </TransitionGroup>
      <DocCommentList v-if="listOpen && hasThreads" />
    </div>
  </div>
</template>
