<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import { ref } from 'vue'
import {
  DEV_PALETTE,
  devPalette,
  resetDevPalette,
  saveDevPalette,
  type DevPaletteRole,
} from '../lib/devPalette'
import './devColorPanel.css'

const open = ref(false)
const copied = ref(false)
let copiedTimer: ReturnType<typeof setTimeout> | undefined

function setColor(key: (typeof DEV_PALETTE)[number]['key'], role: DevPaletteRole, event: Event) {
  devPalette[key][role].color = (event.target as HTMLInputElement).value
  saveDevPalette()
}

function setOpacity(key: (typeof DEV_PALETTE)[number]['key'], role: DevPaletteRole, event: Event) {
  const input = event.target as HTMLInputElement
  const value = Math.max(0, Math.min(100, Number(input.value) || 0))
  input.value = String(value)
  devPalette[key][role].opacity = value / 100
  saveDevPalette()
}

async function copyColors(): Promise<void> {
  const lines = DEV_PALETTE.map((item) => {
    const values = (['card', 'box', 'tick'] as DevPaletteRole[]).map((role) => {
      const value = devPalette[item.key][role]
      return `${role}=${value.color} ${Math.round(value.opacity * 100)}%`
    })
    return `${item.label}: ${values.join(' | ')}`
  })
  const text = `Verticals developer colors\n${lines.join('\n')}`
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    textarea.remove()
  }
  copied.value = true
  if (copiedTimer) clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => { copied.value = false }, 2000)
}
</script>

<template>
  <button
    type="button"
    class="dev-color-panel__trigger"
    aria-label="Open developer color panel"
    :aria-expanded="open"
    @click="open = !open"
  >Colors</button>

  <aside v-if="open" class="dev-color-panel" data-role="dev-color-panel" aria-label="Developer colors">
    <header class="dev-color-panel__header">
      <div>
        <strong>Developer colors</strong>
        <p>Live preview only. Saved in this browser.</p>
      </div>
      <button type="button" class="dev-color-panel__close" aria-label="Close color panel" @click="open = false"><AppIcon name="x" :size="16" /></button>
    </header>
    <div class="dev-color-panel__legend">
      <span>Card</span><span>Box</span><span>Tick</span>
    </div>
    <div v-for="item in DEV_PALETTE" :key="item.key" class="dev-color-panel__row">
      <span class="dev-color-panel__name">
        <i :style="{ backgroundColor: item.source }" aria-hidden="true" />
        {{ item.label }}
      </span>
      <label v-for="role in ['card', 'box', 'tick'] as DevPaletteRole[]" :key="role" class="dev-color-panel__picker">
        <span class="sr-only">{{ item.label }} {{ role }} color</span>
        <input type="color" :value="devPalette[item.key][role].color" @input="setColor(item.key, role, $event)">
        <span class="dev-color-panel__opacity-field">
          <input
            type="number"
            min="0"
            max="100"
            step="1"
            inputmode="numeric"
            :value="Math.round(devPalette[item.key][role].opacity * 100)"
            :aria-label="`${item.label} ${role} opacity percentage`"
            @input="setOpacity(item.key, role, $event)"
          >
          <small>%</small>
        </span>
      </label>
    </div>
    <div class="dev-color-panel__actions">
      <button type="button" class="dev-color-panel__copy" @click="copyColors">{{ copied ? 'Copied' : 'Copy colours' }}</button>
      <button type="button" class="dev-color-panel__reset" @click="resetDevPalette">Reset selected colors</button>
    </div>
  </aside>
</template>
