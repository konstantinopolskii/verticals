<script setup lang="ts">
/* Product-level add row. Rest renders the board's disabled-checkbox grid; activation replaces
   that row in place with the existing one-input create path.

   WP-22: no more local id generation. WP-12 had no backend, so this minted a fake `local-...` id
   just to give its parent's local list a React/Vue `:key`; now the real id comes back from
   `POST /api/goals` (`store.ts::createGoalOn`, via `Column.vue`), and a client-invented id would
   only ever be wrong. This component's job shrinks to exactly what S-65 (L8) requires of it: one
   input, zero required selects, and forwarding a committed title string. */
import { nextTick, ref, useAttrs } from 'vue'

defineOptions({ inheritAttrs: false })
withDefaults(defineProps<{ placeholder?: string }>(), { placeholder: 'Add…' })
const emit = defineEmits<{ add: [title: string] }>()
const attrs = useAttrs()
const editing = ref(false)
const draft = ref('')
const editor = ref<HTMLInputElement | null>(null)

function openEditor() {
  editing.value = true
  void nextTick(() => editor.value?.focus())
}

function cancelEditor() {
  draft.value = ''
  editing.value = false
}

function commit() {
  const title = draft.value.trim()
  if (!title) return
  emit('add', title)
  cancelEditor()
}

function onBlur() {
  if (!draft.value.trim()) cancelEditor()
}
</script>

<template>
  <div
    v-bind="attrs"
    data-role="column-add"
    class="column-add-row"
    :role="editing ? undefined : 'button'"
    :tabindex="editing ? undefined : 0"
    @click="!editing && openEditor()"
    @keydown.enter.prevent="!editing && openEditor()"
    @keydown.space.prevent="!editing && openEditor()"
  >
    <label class="checkbox checkbox--size-s column-add-row__checkbox" aria-hidden="true">
      <input class="checkbox__input" type="checkbox" disabled>
      <span class="checkbox__box" />
    </label>
    <input
      v-if="editing"
      ref="editor"
      v-model="draft"
      data-role="column-add-editor"
      class="column-add-editor"
      type="text"
      :placeholder="placeholder"
      aria-label="Add goal"
      @click.stop
      @keydown.space.stop
      @keydown.enter.prevent="commit"
      @keydown.esc.stop.prevent="cancelEditor"
      @blur="onBlur"
    >
    <span v-else class="column-add-row__text">{{ placeholder }}</span>
  </div>
</template>

<style>
.column-add-row {
  display: flex;
  width: 100%;
  min-height: 34px;
  min-width: 0;
  box-sizing: border-box;
  margin: 0;
  /* The card shell has a six-pixel outer pad, then its text starts 16px into the body. Keep the
     add affordance aligned to that same content edge rather than to the shell boundary. */
  padding: 6px var(--space-4);
  border: 0;
  border-radius: 8px;
  background: #fff;
  color: rgb(45 48 54 / 52%);
  font-family: inherit;
  font-size: 15px;
  line-height: 22px;
  font-weight: 400;
  transition: background-color var(--motion-hover) cubic-bezier(.165, .84, .44, 1);
}
.column-add-row {
  align-items: flex-start;
  cursor: pointer;
}
.column-add-row:hover {
  background: rgb(45 48 54 / 6%);
  color: rgb(45 48 54 / 72%);
  outline: none;
}
.column-add-row:active {
  background: rgb(45 48 54 / 11%);
  color: rgb(45 48 54 / 88%);
  outline: none;
}
.column-add-row:focus-visible {
  background: rgb(45 48 54 / 6%);
  color: rgb(45 48 54 / 72%);
  outline: 2px solid var(--color-border-strong);
  outline-offset: 1px;
}
.column-add-row__checkbox {
  flex: 0 0 16px;
  position: relative;
  top: 4px;
  left: -2px;
  pointer-events: none;
}
.column-add-row__checkbox .checkbox__box {
  border: 0;
  /* D225: swapped with the no-colour goal box — the add placeholder sits lighter (242) than
     committed colourless items (#e5e5e5). */
  background: rgb(242 242 242);
  box-shadow: inset 0 1px 1px rgb(0 0 0 / 12%);
}
.column-add-row__text {
  min-width: 0;
  padding: 0 6px 0 6px;
  word-break: break-word;
}
.column-add-editor {
  flex: 1 1 auto;
  min-width: 0;
  margin: 0;
  padding: 0 6px 0 6px;
  border: 0;
  outline: none;
  background: transparent;
  color: inherit;
  font: inherit;
}
</style>
