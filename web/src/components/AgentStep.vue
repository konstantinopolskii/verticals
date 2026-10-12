<script setup lang="ts">
// The step (docs/design-handoff S2.P3; docs/design/morning-quality.md): while the agent works, one fixed phrase of what it is
// doing, written inside the field beside the turning line. The field widens into a pill for it (SearchBar.vue); the phrase
// used to stand in a bubble above the circle. A phrase stays at least 150 ms, so a fast turn never flickers.
import { onBeforeUnmount, ref, watch } from 'vue'
import { agentChat } from '../lib/agentChat'
import './agentStep.css'

const props = defineProps<{ shown: boolean }>()

const words = ref(agentChat.step)
let since = 0
let timer: ReturnType<typeof setTimeout> | null = null
watch(() => agentChat.step, (step) => {
  if (timer) clearTimeout(timer)
  const wait = Math.max(0, 150 - (performance.now() - since))
  timer = setTimeout(() => { words.value = step; since = performance.now() }, wait)
})
// It comes in with the phrase the agent is on, not the one it was on when it last stood here.
watch(() => props.shown, (on) => {
  if (!on) return
  if (timer) clearTimeout(timer)
  words.value = agentChat.step
  since = performance.now()
})
onBeforeUnmount(() => { if (timer) clearTimeout(timer) })
</script>

<template>
  <Transition name="agent-step">
    <span v-if="shown" class="circle-field__step" data-role="agent-step" role="status" aria-live="polite">
      <Transition name="agent-step-words" mode="out-in">
        <span :key="words" class="circle-field__step-words">{{ words }}</span>
      </Transition>
    </span>
  </Transition>
</template>
