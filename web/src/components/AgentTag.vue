<script setup lang="ts">
// The agent tag above the field (docs/design-handoff S2.P2): the monochrome mark of the agent that answers and a
// chevron; its menu is today's agent picker as it is (agent, model, effort, speed, permissions, usage), with
// "New conversation" on top until the history comes.
import { computed, onBeforeUnmount, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { agentChat, agentOf, assetUrl, choose, loadProbe, newThread, refreshAgents, type ModelChoice } from '../lib/agentChat'

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const hoverDetail = ref<string | null>(null)
const selection = computed(() => agentChat.selection)
const agent = computed(() => agentOf(selection.value?.provider))
const probe = computed(() => agentChat.probes[selection.value?.provider ?? ''] ?? { models: [] })
const models = computed<ModelChoice[]>(() => {
  const list = probe.value.models ?? []
  const saved = selection.value?.model
  return saved && !list.some((model) => model.value === saved) ? [{ value: saved, label: saved, detail: 'Your saved choice' }, ...list] : list
})
const permission = computed(() => agent.value.permissions.find((p) => p.value === selection.value?.permission))
const footer = computed(() => hoverDetail.value || permission.value?.detail || 'Applies to your next message.')

function toggle(): void {
  open.value = !open.value
  if (!open.value) return
  hoverDetail.value = null
  if (selection.value) void loadProbe(selection.value.provider, true)
  void refreshAgents()
  document.addEventListener('pointerdown', onOutside, true)
}
function close(): void {
  open.value = false
  document.removeEventListener('pointerdown', onOutside, true)
}
function onOutside(event: PointerEvent): void {
  if (!root.value?.contains(event.target as Node)) close()
}
function startNew(): void {
  newThread()
  agentChat.history = []
  close()
}
onBeforeUnmount(() => document.removeEventListener('pointerdown', onOutside, true))
</script>

<template>
  <div v-if="agentChat.available && selection" ref="root" class="agent-tag-wrap">
    <button
      type="button"
      class="circle-tag agent-tag"
      data-tag="agent"
      :aria-label="`Agent: ${agent.label}`"
      :aria-expanded="open"
      @click="toggle"
      @keydown.esc.stop="close"
    >
      <img class="agent-tag__mark" alt="" :src="assetUrl(agent.image)">
      <span class="circle-tag__name">{{ agent.label.replace(' Code', '') }}</span>
      <AppIcon name="chevron-down" :size="12" :stroke="2.6" />
    </button>
    <div v-if="open" class="agent-picker vt-shadow vt-shadow--small" role="dialog" aria-label="Agent settings" @keydown.esc.stop="close">
      <button type="button" class="agent-picker__new" data-role="new-conversation" @click="startNew">
        <AppIcon name="plus" :size="14" /> New conversation
      </button>
      <div class="agent-picker__columns">
        <section>
          <h2>Agent</h2>
          <div v-for="item in agentChat.agents" :key="item.id">
            <button type="button" class="agent-picker__choice" :aria-pressed="item.id === selection.provider" :disabled="!item.available"
              @click="choose({ provider: item.id })">
              <img alt="" :src="assetUrl(item.image)"><span>{{ item.label }}<small v-if="!item.available">Not installed</small></span>
            </button>
            <div v-if="item.id === selection.provider" class="agent-picker__usage">
              <p v-if="!probe.usage || probe.loading">Loading usage…</p>
              <p v-else-if="probe.usage.state !== 'ready'">Usage unavailable</p>
              <template v-else>
                <div v-for="w in probe.usage.windows" :key="w.label" class="agent-picker__quota">
                  <span>{{ w.label }}</span><span>{{ w.remainingPercent }}% left</span>
                  <i :style="{ width: `${w.remainingPercent}%` }"></i>
                </div>
              </template>
            </div>
          </div>
        </section>
        <section>
          <h2>Model</h2>
          <p v-if="probe.loading && !models.length" class="agent-picker__status">Loading models…</p>
          <p v-else-if="!models.length" class="agent-picker__status">No models available</p>
          <button v-for="model in models" :key="model.value" type="button" class="agent-picker__choice"
            :aria-pressed="model.value === selection.model" :disabled="probe.loading"
            @mouseenter="hoverDetail = model.detail || null" @click="choose({ model: model.value })">
            <span>{{ model.label }}</span>
          </button>
          <p v-if="probe.modelsError" class="agent-picker__status">{{ probe.modelsError }}</p>
        </section>
        <section>
          <h2>Effort</h2>
          <button v-for="effort in agent.efforts" :key="effort.value" type="button" class="agent-picker__choice"
            :aria-pressed="effort.value === selection.effort" @click="choose({ effort: effort.value })">
            <span>{{ effort.label }}</span>
          </button>
        </section>
        <section>
          <h2>Speed</h2>
          <button type="button" class="agent-picker__choice" :aria-pressed="!selection.fast" @click="choose({ fast: false })"><span>Standard</span></button>
          <button type="button" class="agent-picker__choice" :aria-pressed="selection.fast" @mouseenter="hoverDetail = agent.fast || null"
            @click="choose({ fast: true })"><span>Fast</span></button>
        </section>
        <section>
          <h2>Permissions</h2>
          <button v-for="p in agent.permissions" :key="p.value" type="button" class="agent-picker__choice"
            :aria-pressed="p.value === selection.permission" @mouseenter="hoverDetail = p.detail" @click="choose({ permission: p.value })">
            <span>{{ p.label }}</span>
          </button>
        </section>
      </div>
      <p class="agent-picker__footer">{{ footer }}</p>
    </div>
  </div>
</template>

<style>
.agent-tag-wrap { position: relative; }
.agent-tag { gap: 2px; }
.agent-tag__mark { width: 16px; height: 16px; filter: brightness(0) invert(1); }
.agent-picker {
  position: absolute;
  left: 0;
  bottom: 36px;
  z-index: 10;
  box-sizing: border-box;
  width: min(760px, calc(100vw - 32px));
  padding: 8px;
  border-radius: 14px;
  background: #fff;
  color: #000;
  font: 400 13px/18px var(--font-body);
}
.agent-picker__new {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  font: 500 14px/20px var(--font-body);
  text-align: left;
  cursor: pointer;
}
.agent-picker__new:hover { background: rgb(0 0 0 / 5%); }
.agent-picker__columns { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 4px; max-height: 360px; overflow: auto; }
.agent-picker h2 { margin: 8px 10px 4px; color: rgb(0 0 0 / 45%); font: 500 11px/16px var(--font-body); }
.agent-picker__choice {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 6px 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.agent-picker__choice img { width: 16px; height: 16px; }
.agent-picker__choice small { display: block; color: rgb(0 0 0 / 45%); font-size: 11px; }
.agent-picker__choice:hover:not(:disabled) { background: rgb(0 0 0 / 5%); }
.agent-picker__choice[aria-pressed='true'] { font-weight: 600; }
.agent-picker__choice:disabled { opacity: .45; cursor: default; }
.agent-picker__usage, .agent-picker__status { margin: 2px 10px 6px; color: rgb(0 0 0 / 50%); font-size: 11px; }
.agent-picker__usage p { margin: 0; }
.agent-picker__quota { position: relative; display: flex; justify-content: space-between; padding-bottom: 5px; }
.agent-picker__quota i { position: absolute; left: 0; bottom: 0; height: 2px; border-radius: 1px; background: #000; }
.agent-picker__footer { margin: 6px 10px 2px; color: rgb(0 0 0 / 55%); font-size: 12px; }
</style>
