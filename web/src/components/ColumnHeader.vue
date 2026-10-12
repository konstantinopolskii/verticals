<script setup lang="ts">
/* Deliberately NOT KCardHeading: that component wraps output in div.card__heading, which carries
   its own margin-top (--space-2) and left/right padding (--card-inset-x) — exactly what the A7
   kit commit replaced with .pattern-vertical-board__header{padding:24px 8px 0 12px} to hit the
   measured baseline offset. Using KCardHeading here would double up padding and throw off the
   probe. A7's own commit message says as much: reuse the kit's .t-title/.t-caption utilities
   directly, no new/reused component wrapper. */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { fittest, fontEpoch, fontOf } from '../lib/fitName'
import type { NameForm } from '../types'
import './columnHeader.css'

const props = withDefaults(defineProps<{
  title: string
  subLabel?: string
  /** The same name in shorter forms, longest first: the header shows the first that fits its room, so a name is never
   *  cut with "…" (docs/design/column-names.md, `lib/fitName.ts`). */
  shorter?: NameForm[]
  /** A span's end, after its date (docs/design-handoff S5.P1.014). */
  end?: string
}>(), { subLabel: '', shorter: () => [], end: '' })

const emit = defineEmits<{ form: [form: NameForm] }>()

/* The name's room is the width of its row, which a column that opens, closes or is resized changes in the frame its
   layout does: the observer reports it before that frame is drawn, and the form that fits is chosen there, never while
   the column moves. (The row, not the title: the title is a few px wider than its room, see `--column-spill` below.) */
const rowEl = ref<HTMLElement | null>(null)
const titleEl = ref<HTMLElement | null>(null)
const room = ref(0)
let watcher: ResizeObserver | null = null
onMounted(() => {
  if (!rowEl.value || typeof ResizeObserver === 'undefined') return
  watcher = new ResizeObserver((entries) => { room.value = entries[entries.length - 1].contentRect.width })
  watcher.observe(rowEl.value)
})
onBeforeUnmount(() => watcher?.disconnect())

const forms = computed<NameForm[]>(() => [{ name: props.title, kind: props.subLabel }, ...props.shorter])
const shown = computed<NameForm>(() => {
  fontEpoch.value // chosen again once the title font has arrived
  const all = forms.value
  if (all.length === 1 || !titleEl.value || room.value <= 0) return all[0]
  return all[fittest(all.map((form) => form.name), room.value, fontOf(titleEl.value))]
})
/* The line pinned at the column's top says the same words once the name has scrolled under it, so it is told which form
   fits (docs/design/column-bars.md). */
watch(shown, (form) => emit('form', form), { immediate: true })
</script>

<template>
  <header class="pattern-vertical-board__header column-header">
    <div v-if="shown.kind" class="column-header__period-row">
      <p class="t-caption column-header__sub-label">{{ shown.kind }}</p>
    </div>
    <div ref="rowEl" class="column-header__title-row">
      <!-- A shorter form on screen still has the full name for a screen reader. -->
      <h3 ref="titleEl" class="t-title" :aria-label="shown === forms[0] ? undefined : title">{{ shown.name }}<span v-if="end" class="column-header__end" data-role="span-end">{{ end }}</span></h3>
    </div>
  </header>
</template>
