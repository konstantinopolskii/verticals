<script setup lang="ts">
// A document as a page on the desk (round 2's sheet, KK 6 Oct 2026: "как документы в Pages отображались, сразу с превью
// текста … вроде и иконка а вроде объект"): the document's own top, its window's one-line head and its title over its
// first words, set at the window's 720 px and drawn at the page's size, so its text is the page's texture.
import { computed, onMounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import type { DeskDoc } from '../lib/api'
import { renderBodyElement } from '../lib/bodyMarkdown'
import { shortDay } from '../lib/docsDesk'

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

<style>
.doc-page { position: relative; overflow: hidden; border-radius: 5px; background: #fff; text-align: left;
  box-shadow: 0 0 0 .5px rgba(16, 18, 32, .07), 0 1px 3px rgba(16, 18, 32, .06), 0 10px 24px -10px rgba(16, 18, 32, .2); }
.doc-page__in { position: absolute; left: 0; top: 0; width: 720px; height: 960px; transform-origin: 0 0; pointer-events: none; }
.doc-page__bar { display: flex; align-items: center; gap: 8px; height: 52px; padding: 0 24px; font: 400 13px/20px var(--font-body, Commissioner, system-ui, sans-serif);
  color: rgba(0, 0, 0, .5); }
.doc-page__bar .app-icon { color: rgba(0, 0, 0, .38); }
.doc-page__text { padding: 0 48px; font: 400 16px/24px var(--font-body, Commissioner, system-ui, sans-serif); color: #000; }
.doc-page__text h1 { margin: 20px 0 16px; font: 700 28px/34px var(--font-body, Commissioner, system-ui, sans-serif); }
.doc-page__text h2, .doc-page__text h3, .doc-page__text h4 { margin: 22px 0 8px; font: 600 18px/26px var(--font-body, Commissioner, system-ui, sans-serif); }
.doc-page__text p { margin: 0 0 12px; }
.doc-page__text ul, .doc-page__text ol { margin: 0 0 12px; padding-left: 22px; }
.doc-page__text table { width: 100%; margin: 0 0 12px; border-collapse: collapse; font-size: 13px; line-height: 18px; }
.doc-page__text th, .doc-page__text td { padding: 6px 8px; border-bottom: 1px solid rgba(45, 48, 54, .12); text-align: left; vertical-align: top; }
.doc-page__text img { display: none; }
/* Set narrow, the page keeps a readable title (round 5's `.wpage`): no head, the title first, its facts under it, the
   text's margins shrunk. */
.doc-page__in--narrow .doc-page__text { padding: 22px 24px; }
.doc-page__in--narrow .doc-page__text h1 { margin: 0 0 4px; }
.doc-page__facts.doc-page__facts { margin: 0 0 14px; font: 400 13px/20px var(--font-body, Commissioner, system-ui, sans-serif); color: rgba(0, 0, 0, .5); }
</style>
