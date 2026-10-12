<script setup lang="ts">
// A document as a page on the desk (round 2's sheet, KK 6 Oct 2026: "как документы в Pages отображались, сразу с превью
// текста … вроде и иконка а вроде объект"): the document's own top, its window's one-line head and its title over its
// first words, set at the window's 720 px and drawn at the page's size, so its text is the page's texture.
import { computed, onMounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import type { DeskDoc } from '../lib/api'
import { renderBodyElement } from '../lib/bodyMarkdown'
import { shortDay } from '../lib/docsDesk'
import './docPage.css'

/** measure: the width the page is set at before it is drawn at `width`; the window's 720 on the desk, a narrow 300 for a
 *  page waiting on the circle, so its title reads (round 4's `.wpage`). */
const props = withDefaults(defineProps<{ doc: Pick<DeskDoc, 'title' | 'path' | 'excerpt' | 'updated_at'>; width?: number; measure?: number; facts?: string }>(),
  { width: 120, measure: 720, facts: '' })
const body = ref<HTMLElement | null>(null)

function render(): void {
  const el = body.value
  if (!el) return
  el.replaceChildren()
  // The title stands large above; a first "# title" line in the text would say it twice.
  renderBodyElement(el, props.doc.excerpt.replace(/^\s*#\s[^\n]*\n?/, ''))
}
/* The page's one line of facts: in the window's head on a desk page; under the title on a narrow page waiting on the
   circle (round 5's `.wpage`, frame m1). */
const line = computed(() => props.facts || `edited ${shortDay(props.doc.updated_at)}`)
onMounted(render)
watch(() => props.doc.excerpt, render)
</script>

<template>
  <div class="doc-page" :style="{ width: `${width}px`, height: `${Math.round(width * 4 / 3)}px` }" aria-hidden="true">
    <div class="doc-page__in" :class="{ 'doc-page__in--narrow': measure < 720 }" :style="{ width: `${measure}px`, height: `${Math.round(measure * 4 / 3)}px`, transform: `scale(${width / measure})` }">
      <div v-if="measure >= 720" class="doc-page__bar"><AppIcon name="file" :size="16" />{{ line }}</div>
      <div class="doc-page__text">
        <h1>{{ doc.title || doc.path }}</h1>
        <p v-if="measure < 720" class="doc-page__facts">{{ line }}</p>
        <div ref="body"></div>
      </div>
    </div>
  </div>
</template>
