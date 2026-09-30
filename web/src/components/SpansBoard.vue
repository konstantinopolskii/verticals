<script setup lang="ts">
// The weeks under your hand (docs/design-handoff S5.P1): the spans in a row at the regular columns' width, one loaded
// beyond each edge and out of view, and the floating column wide at its side, 2 px from the window's edges. A step moves
// the row by one span (S5.P1.025); the columns come in from the corner held (S5.P1.023).
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import Column from './Column.vue'
import { store } from '../store'
import { spans, spanColumns, spanWidth } from '../lib/spans'
import { reducedMotion, timing } from '../lib/motion'

const row = ref<HTMLElement | null>(null)
const width = computed(() => spanWidth())
const floating = computed(() => store.columns.value.find((column) => column.vertical === spans.floating) ?? null)

/* The columns slide into the spans from the corner held, and the floating column slides to its side and lifts; with
   reduced motion they fade in (S5.P1.023). */
const float = ref<HTMLElement | null>(null)
onMounted(() => {
  const held = spans.heldAt
  const box = row.value?.getBoundingClientRect()
  if (reducedMotion()) {
    for (const el of [row.value, float.value]) el?.animate([{ opacity: 0 }, { opacity: 1 }], timing(120, 'large'))
    return
  }
  if (box && held !== null) {
    row.value?.animate([{ transform: `translateX(${held - box.right}px)`, opacity: 0 }, { transform: 'none', opacity: 1 }], timing(400, 'large'))
  }
  const side = spans.side === 'right' ? 1 : -1
  float.value?.animate([{ transform: `translateX(${-side * 120}px) scale(.96)`, opacity: 0 }, { transform: 'none', opacity: 1 }], timing(400, 'large'))
})

/* One span on or back: the row keeps its place for a frame, then slides by one span (S5.P1.025). */
watch(() => spans.offset, async (now, was) => {
  if (was === undefined || now === was) return
  await nextTick()
  row.value?.animate(
    [{ transform: `translateX(${(now - was) * width.value}px)` }, { transform: 'translateX(0)' }],
    timing(300, 'large'),
  )
})
</script>

<template>
  <div class="spans-board" :class="`spans-board--float-${spans.side}`" data-role="spans-board" :data-vertical="spans.vertical ?? ''">
    <div class="spans-board__view">
      <div
        ref="row"
        class="card-stack pattern-vertical-board pattern-vertical-board--flat spans-board__row"
        :style="{ width: `${spanColumns.length * width}px` }"
        data-role="spans-row"
      >
        <Column
          v-for="span in spanColumns"
          :key="span.start"
          :vertical="span.column.vertical"
          :title="span.date"
          :sub-label="span.how"
          :end="span.end"
          :goals="span.column.goals"
          :period-key="span.column.periodKey"
          span
          :data-span-start="span.start"
        />
      </div>
    </div>
    <div
      v-if="floating"
      ref="float"
      class="card-stack pattern-vertical-board pattern-vertical-board--flat spans-board__float vt-shadow"
      data-role="spans-floating"
    >
      <Column
        :vertical="floating.vertical"
        :title="floating.title"
        :sub-label="floating.subLabel"
        :goals="floating.goals"
        :period-key="floating.periodKey"
        :add-placeholder="floating.addPlaceholder"
        active
      />
    </div>
  </div>
</template>

<style>
.spans-board {
  position: fixed;
  inset: 0;
  z-index: 40;
  display: flex;
  background: var(--color-bg);
}
/* Empty periods are common here: their add row stands on the page, not on the kit's first-card fill. */
.spans-board .column-add-row { background: transparent; }
.spans-board__view { flex: 1 1 auto; min-width: 0; overflow: clip; }
.spans-board--float-left .spans-board__view { order: 2; }
.spans-board__row.spans-board__row { height: 100%; overflow: clip; flex-wrap: nowrap; }
.spans-board__row.spans-board__row > .pattern-vertical-board__column { flex: 1 1 0; min-width: 0; max-width: none; }
.spans-board__float.spans-board__float {
  flex: 0 0 400px;
  box-sizing: border-box;
  height: calc(100% - 4px);
  margin: 2px 2px 2px 0;
  overflow: clip;
  border-radius: 16px;
  background: #fff;
}
.spans-board--float-left .spans-board__float.spans-board__float { order: 1; margin: 2px 0 2px 2px; }
.spans-board__float.spans-board__float > .pattern-vertical-board__column {
  flex: 1 1 auto;
  min-width: 0;
  max-width: none;
  padding-inline: 14px;
}
</style>
