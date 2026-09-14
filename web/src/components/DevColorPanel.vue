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

<style>
.dev-color-panel__trigger {
  position: fixed;
  right: 16px;
  bottom: 16px;
  z-index: 300;
  height: 32px;
  padding: 0 12px;
  border: 1px solid rgb(45 48 54 / 18%);
  border-radius: 6px;
  background: rgb(255 255 255 / 92%);
  color: rgb(45 48 54 / 72%);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgb(0 0 0 / 8%);
}
.dev-color-panel__trigger:hover,
.dev-color-panel__reset:hover,
.dev-color-panel__close:hover { background: rgb(45 48 54 / 7%); }
.dev-color-panel {
  position: fixed;
  right: 16px;
  bottom: 56px;
  z-index: 301;
  width: 370px;
  max-height: min(620px, calc(100vh - 80px));
  box-sizing: border-box;
  overflow: auto;
  padding: 14px;
  border: 1px solid rgb(45 48 54 / 14%);
  border-radius: 8px;
  background: #fff;
  color: rgb(45 48 54);
  box-shadow: 0 8px 30px rgb(0 0 0 / 16%);
}
.dev-color-panel__header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 12px; }
.dev-color-panel__header strong { font-size: 14px; font-weight: 600; }
.dev-color-panel__header p { margin: 3px 0 0; color: rgb(45 48 54 / 52%); font-size: 11px; }
.dev-color-panel__close { border: 0; background: transparent; color: rgb(45 48 54 / 55%); font-size: 20px; line-height: 18px; cursor: pointer; }
.dev-color-panel__legend { display: grid; grid-template-columns: minmax(0, 1fr) repeat(3, 64px); gap: 8px; margin-bottom: 4px; color: rgb(45 48 54 / 45%); font-size: 10px; text-align: center; }
.dev-color-panel__row { display: grid; grid-template-columns: minmax(0, 1fr) repeat(3, 64px); align-items: center; gap: 8px; min-height: 48px; border-top: 1px solid rgb(45 48 54 / 8%); }
.dev-color-panel__name { display: flex; align-items: center; gap: 7px; font-size: 12px; }
.dev-color-panel__name i { width: 12px; height: 12px; border-radius: 3px; box-shadow: inset 0 1px 1px rgb(0 0 0 / 16%); }
.dev-color-panel__picker { display: flex; width: 64px; height: 40px; flex-direction: column; align-items: center; justify-content: center; gap: 1px; }
.dev-color-panel__picker input[type="color"] { width: 24px; height: 22px; padding: 0; border: 0; background: transparent; cursor: pointer; }
.dev-color-panel__opacity-field { display: flex; align-items: center; gap: 2px; }
.dev-color-panel__opacity-field input { width: 42px; height: 18px; box-sizing: border-box; padding: 1px 3px; border: 1px solid rgb(45 48 54 / 16%); border-radius: 3px; background: #fff; color: rgb(45 48 54); font: inherit; font-size: 10px; text-align: right; }
.dev-color-panel__opacity-field small { color: rgb(45 48 54 / 48%); font-size: 10px; }
.dev-color-panel__actions { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-top: 12px; }
.dev-color-panel__copy,
.dev-color-panel__reset { width: 100%; margin-top: 12px; padding: 6px 8px; border: 0; border-radius: 5px; background: transparent; color: rgb(45 48 54 / 66%); font: inherit; font-size: 11px; cursor: pointer; }
.dev-color-panel__actions .dev-color-panel__copy,
.dev-color-panel__actions .dev-color-panel__reset { margin-top: 0; }
.dev-color-panel__copy:hover { background: rgb(45 48 54 / 7%); }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
</style>
