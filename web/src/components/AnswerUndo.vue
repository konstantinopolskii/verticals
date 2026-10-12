<script setup lang="ts">
// An agent's answer has its own Undo (docs/design/agent-answer-undo.md), at the answer's end, in the look of the notice's Undo
// (`FieldNotice.vue`): a white pill. Pressed, it takes back what the answer wrote and is still as the answer left it, and
// becomes Redo. An answer that changed nothing on the board has none; one that could not be taken back any more has none.
import { computed } from 'vue'
import { answerUndo, putBack, takeBack } from '../lib/answerUndo'
import './answerUndo.css'

/* `stays`: the pill is on the answer's message, which stays in front of the person while the answer is taken back, so the notice
   that says what happened has no button of its own. The field's pill goes under the notice, which then is the button. */
const props = defineProps<{ answer?: string | null; stays?: boolean }>()
const entry = computed(() => (props.answer ? answerUndo.entries[props.answer] : undefined))
const undone = computed(() => entry.value?.state === 'undone')

function press(): void {
  if (entry.value) void (undone.value ? putBack(entry.value.id, props.stays) : takeBack(entry.value.id, props.stays))
}
</script>

<template>
  <button
    v-if="entry && entry.state !== 'spent'"
    type="button"
    class="field-notice__action answer-undo"
    data-role="answer-undo"
    :data-state="entry.state"
    :disabled="entry.busy"
    @click.stop="press"
  >{{ undone ? 'Redo' : 'Undo' }}</button>
</template>
