<script setup lang="ts">
import { nextTick, ref } from 'vue'

const props = withDefaults(defineProps<{
  commitOnEnter?: boolean
  showTrigger?: boolean
}>(), {
  commitOnEnter: false,
  showTrigger: true,
})

const emit = defineEmits<{
  commit: [title: string]
}>()

const editing = ref(false)
const draft = ref('')
const editor = ref<HTMLTextAreaElement | null>(null)

function openEditor() {
  editing.value = true
  void nextTick(() => editor.value?.focus())
}

function cancelEditor() {
  draft.value = ''
  editing.value = false
}

function onBlur() {
  if (!draft.value.trim()) cancelEditor()
}

function onEnter() {
  if (!props.commitOnEnter) return
  const title = draft.value.trim()
  if (!title) return
  emit('commit', title)
  cancelEditor()
}

defineExpose({ openEditor })
</script>

<template>
  <!-- The checkbox stays while the step is typed, as in a column's own add row (KK, 29 Sep 2026: "the checkbox doesn't
       disappear"). -->
  <div v-if="editing" class="subgoal-add-editor-shell">
    <label class="checkbox checkbox--size-s subgoal-add-row__checkbox" aria-hidden="true">
      <input class="checkbox__input" type="checkbox" disabled />
      <span class="checkbox__box" />
    </label>
    <textarea
      ref="editor"
      v-model="draft"
      data-role="subgoal-add-editor"
      class="subgoal-add-editor"
      rows="1"
      aria-label="Add subgoal"
      placeholder="Subtask"
      @keydown.enter.prevent="onEnter"
      @keydown.esc.stop.prevent="cancelEditor"
      @blur="onBlur"
    />
  </div>
  <div
    v-else-if="props.showTrigger"
    data-role="subgoal-add"
    class="subgoal-add-row"
    role="button"
    tabindex="0"
    @click="openEditor"
    @keydown.enter.prevent="openEditor"
    @keydown.space.prevent="openEditor"
  >
    <label class="checkbox checkbox--size-s subgoal-add-row__checkbox" aria-hidden="true">
      <input class="checkbox__input" type="checkbox" disabled />
      <span class="checkbox__box" />
    </label>
    <span class="subgoal-add-row__text">Add...</span>
  </div>
</template>

<style>
.subgoal-add-row {
  display: flex;
  width: 100%;
  height: 34px;
  min-width: 0;
  box-sizing: border-box;
  align-items: flex-start;
  margin: 0;
  padding: 6px var(--space-4);
  border: 0;
  border-radius: 8px;
  background: #fff;
  color: inherit;
  font-family: inherit;
  font-size: 15px;
  line-height: 22px;
  font-weight: 400;
  transition: background-color var(--motion-hover) cubic-bezier(.165, .84, .44, 1);
  opacity: .5;
  cursor: pointer;
}
.subgoal-add-row:hover,
.subgoal-add-row:active,
.subgoal-add-row:focus-visible {
  background: var(--color-surface-overlay);
  opacity: 1;
  outline: none;
}
.subgoal-add-row__checkbox {
  flex: 0 0 16px;
  position: relative;
  top: 2px;
  left: -2px;
  pointer-events: none;
}
.subgoal-add-row__text {
  min-width: 0;
  padding: 0 6px 0 6px;
  word-break: break-word;
}
.subgoal-add-editor {
  display: block;
  width: 100%;
  height: 34px;
  box-sizing: border-box;
  margin: 0;
  padding: 0;
  resize: none;
  overflow: hidden;
  border: 0;
  border-radius: 8px;
  outline: none;
  background: transparent;
  box-shadow: none;
  color: inherit;
  caret-color: #e3631b;
  font-family: inherit;
  font-size: 15px;
  line-height: 22px;
  font-weight: 400;
}
.subgoal-add-editor-shell {
  display: flex;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  align-items: flex-start;
  gap: 6px;
  padding: 6px var(--space-4);
  color: var(--color-text-muted);
}
.subgoal-add-editor-shell .subgoal-add-editor {
  flex: 1 1 auto;
  min-width: 0;
  color: var(--color-text);
}
</style>
