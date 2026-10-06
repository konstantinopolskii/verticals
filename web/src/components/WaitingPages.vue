<script setup lang="ts">
// The pages that wait on the circle (`lib/waiting.ts`; round 5, frames m1–m2): each the document's own top set narrow,
// so its title reads. Pointed at, a page lifts; a click opens the document as a window over the board (S3.P4). They step
// aside while you type, while the agent talks and while a window is open.
import { computed } from 'vue'
import DocPage from './DocPage.vue'
import { agentChat } from '../lib/agentChat'
import { circle, circleState } from '../lib/circle'
import { openWindow, windows } from '../lib/windows'
import { startWaiting, waitingPages } from '../lib/waiting'

startWaiting()

const shown = computed(() => waitingPages.value.length > 0 && !windows.list.length && !agentChat.open && !circle.moving
  && (circleState.value === 'rest' || circleState.value === 'open'))

function open(docId: string, title: string, event: Event): void {
  openWindow({ kind: 'doc', target: docId, title }, event.currentTarget as Element)
}
</script>

<template>
  <div class="waiting-pages" :class="{ 'is-shown': shown }" data-role="waiting-pages" :aria-hidden="shown ? undefined : 'true'">
    <button
      v-for="page in waitingPages"
      :key="page.taskId"
      type="button"
      class="waiting-pages__page"
      :data-kind="page.kind"
      :data-doc-id="page.docId"
      :aria-label="`Open ${page.title}`"
      :tabindex="shown ? 0 : -1"
      @click="open(page.docId, page.title, $event)"
    >
      <DocPage :doc="page" :width="120" :measure="300" :facts="page.facts" />
    </button>
  </div>
</template>

<style>
/* On the circle: centred over it, 8 px above the field, above the tags when they come in. */
.waiting-pages { position: absolute; left: 50%; bottom: var(--vt-tags-lift, 0px); z-index: 1; display: flex; align-items: flex-end; gap: 8px;
  transform: translate(-50%, 8px); opacity: 0; visibility: hidden; pointer-events: none;
  transition: opacity 160ms ease, transform 300ms cubic-bezier(.22, 1, .36, 1), bottom 160ms ease, visibility 0s linear 160ms; }
.waiting-pages.is-shown { transform: translate(-50%, 0); opacity: 1; visibility: visible; pointer-events: auto;
  transition: opacity 160ms ease, transform 300ms cubic-bezier(.22, 1, .36, 1), bottom 160ms ease, visibility 0s; }
.waiting-pages__page { display: block; padding: 0; border: 0; border-radius: 6px; background: none; cursor: default; }
.waiting-pages__page > .doc-page { border-radius: 6px; transition: transform 160ms cubic-bezier(.2, 0, 0, 1), box-shadow 160ms ease; }
.waiting-pages__page:hover > .doc-page, .waiting-pages__page:focus-visible > .doc-page {
  transform: translateY(-2px) scale(1.03);
  box-shadow: 0 0 0 .5px rgba(16, 18, 32, .07), 0 2px 6px rgba(16, 18, 32, .06), 0 18px 40px -12px rgba(16, 18, 32, .28);
}
@media (prefers-reduced-motion: reduce) { .waiting-pages, .waiting-pages.is-shown, .waiting-pages__page > .doc-page { transition: opacity 160ms ease; } }
</style>
