<script setup lang="ts">
// The step bubble (docs/design-handoff S2.P3): while the agent works, one fixed phrase of what it is doing, above the
// circle where the agent's balloons stand. A phrase stays at least 150 ms, so a fast turn never flickers.
import { onBeforeUnmount, ref, watch } from 'vue'
import { agentChat, openAsk } from '../lib/agentChat'
import { circle } from '../lib/circle'

const shown = ref(agentChat.step)
let since = 0
let timer: ReturnType<typeof setTimeout> | null = null
watch(() => agentChat.step, (step) => {
  if (timer) clearTimeout(timer)
  const wait = Math.max(0, 150 - (performance.now() - since))
  timer = setTimeout(() => { shown.value = step; since = performance.now() }, wait)
})
watch(() => agentChat.running, (running) => { if (running) { shown.value = agentChat.step; since = performance.now() } })
onBeforeUnmount(() => { if (timer) clearTimeout(timer) })
</script>

<template>
  <Transition name="agent-step">
    <div v-if="agentChat.running && !circle.pointed && !openAsk" class="agent-step" data-role="agent-step" role="status" aria-live="polite">
      <Transition name="agent-step-words" mode="out-in">
        <span :key="shown">{{ shown }}</span>
      </Transition>
    </div>
  </Transition>
</template>

<style>
.agent-step {
  position: fixed;
  z-index: 295;
  left: calc(50% - min(281px, 50vw - 16px));
  bottom: calc(24px + var(--vt-field-height, 84px) + 12px);
  padding: 7px 16px 8px;
  border-radius: var(--vt-radius-balloon);
  background: #000;
  color: #fff;
  font: 400 15px/22px var(--font-body);
  white-space: nowrap;
  pointer-events: none;
}
.agent-step-enter-active, .agent-step-leave-active { transition: opacity var(--vt-dur-fade) ease-out; }
.agent-step-enter-from, .agent-step-leave-to { opacity: 0; }
.agent-step-words-enter-active, .agent-step-words-leave-active { transition: opacity 75ms linear; }
.agent-step-words-enter-from, .agent-step-words-leave-to { opacity: 0; }
@media (prefers-reduced-motion: reduce) {
  .agent-step-words-enter-active, .agent-step-words-leave-active { transition: none; }
}
</style>
