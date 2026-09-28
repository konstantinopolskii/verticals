<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import PopoverEngine from '../../components/PopoverEngine.vue'

const props = defineProps<{
  expected: string[] | null
  actual: string[] | null
}>()
const emit = defineEmits<{ changeExpected: [value: string | null] }>()

const compactToken = (token: string) => token === '<5m' ? token : token.replace(/m$/, '')
function formatCompact(shots: string[] | null): string {
  if (!shots?.length) return ''
  const counts = new Map<string, number>()
  for (const shot of shots) counts.set(shot, (counts.get(shot) ?? 0) + 1)
  return [...counts].map(([shot, count]) => `${count}x${compactToken(shot)}`).join(' ')
}

const HUMAN_SHOTS: Record<string, string> = {
  '<5m': '5-min',
  '10-15m': '15-min',
  '45-120m': 'long',
  '240-480m': 'deep',
}

function formatHuman(shots: string[] | null): string {
  if (!shots?.length) return ''
  const counts = new Map<string, number>()
  for (const shot of shots) counts.set(shot, (counts.get(shot) ?? 0) + 1)
  return [...counts].map(([shot, count]) => {
    const name = HUMAN_SHOTS[shot] ?? compactToken(shot)
    return `${count} × ${name} shot${count === 1 ? '' : 's'}`
  }).join(' + ')
}

const summary = computed(() => {
  const expected = formatHuman(props.expected)
  const actual = formatHuman(props.actual)
  if (!expected && !actual) return 'Set shot size…'
  if (!expected) return `Actual ${actual}`
  return actual ? `${expected}, actual ${actual}` : expected
})

const draft = ref(formatCompact(props.expected))
watch(() => props.expected, (value) => { draft.value = formatCompact(value) })

function commit() {
  const value = draft.value.trim()
  if (value !== formatCompact(props.expected)) emit('changeExpected', value || null)
}
</script>

<template>
  <section class="shot-size-fields" data-role="size-fields">
    <PopoverEngine
      placement="top-start"
      :fixed-width="260"
      surface-class="shot-size-fields__popover"
    >
      <template #trigger="{ open }">
        <button
          type="button"
          class="shot-size-fields__summary"
          data-role="size-summary"
          aria-label="Edit shot size"
          :aria-expanded="open"
        >{{ summary }}</button>
      </template>

      <label class="shot-size-fields__field">
        <span class="shot-size-fields__label">Plan</span>
        <input
          v-model="draft"
          class="shot-size-fields__input"
          data-role="size-expected"
          placeholder="1x45-120"
          @keydown.enter.prevent="($event.target as HTMLInputElement).blur()"
          @blur="commit"
        >
      </label>
      <p v-if="actual?.length" class="shot-size-fields__actual" data-role="size-actual">
        <span>Actual</span>
        <strong>{{ formatHuman(actual) }}</strong>
      </p>
    </PopoverEngine>
  </section>
</template>

<style>
.shot-size-fields {
  flex: 1 1 160px;
  min-width: 0;
  color: var(--color-text-muted);
  font-size: 13px;
  line-height: 20px;
}
.shot-size-fields__summary {
  display: block;
  max-width: 100%;
  min-height: 20px;
  padding: 0;
  overflow: hidden;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}
.shot-size-fields__summary:hover { color: var(--color-text); }
.shot-size-fields__summary:focus-visible {
  outline: 2px solid var(--color-border-strong);
  outline-offset: 2px;
}
.shot-size-fields__popover.shot-size-fields__popover {
  gap: 8px;
  padding: 12px;
  user-select: text;
  -webkit-user-select: text;
}
.shot-size-fields__field {
  display: grid;
  gap: 4px;
}
.shot-size-fields__label,
.shot-size-fields__actual > span {
  color: rgba(0, 0, 0, .45);
  font-size: 12px;
  line-height: 16px;
}
.shot-size-fields__input {
  box-sizing: border-box;
  width: 100%;
  height: 28px;
  padding: 4px 8px;
  border: 1px solid rgba(0, 0, 0, .2);
  border-radius: 4px;
  color: inherit;
  font: inherit;
}
.shot-size-fields__actual {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin: 0;
  font-size: 13px;
  line-height: 20px;
}
.shot-size-fields__actual strong { font-weight: 400; }
</style>
