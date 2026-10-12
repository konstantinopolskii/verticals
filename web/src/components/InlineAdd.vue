<script setup lang="ts">
/* Product-level add row. Rest renders the board's disabled-checkbox grid; activation replaces
   that row in place with the existing one-input create path.

   WP-22: no more local id generation. WP-12 had no backend, so this minted a fake `local-...` id
   just to give its parent's local list a React/Vue `:key`; now the real id comes back from
   `POST /api/goals` (`store.ts::createGoalOn`, via `Column.vue`), and a client-invented id would
   only ever be wrong. This component's job shrinks to exactly what S-65 (L8) requires of it: one
   input, zero required selects, and forwarding a committed title string. */
import { nextTick, ref, useAttrs } from 'vue'
import './inlineAdd.css'

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
