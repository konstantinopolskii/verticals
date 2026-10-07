<script setup lang="ts">
import { ref } from 'vue'

// The desktop app's page zoom (desktop/macos/Verticals.swift); a browser has its own ⌘+ and shows no buttons.
type ZoomWindow = Window & {
  webkit?: { messageHandlers?: { zoom?: { postMessage(value: number): void } } }
  verticalsPageZoom?: number
}
const host = window as ZoomWindow
const bridge = host.webkit?.messageHandlers?.zoom
const STEPS = [0.5, 0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2]
const zoom = ref(host.verticalsPageZoom ?? 1)

function set(value: number): void {
  zoom.value = value
  bridge?.postMessage(value)
}

function step(direction: 1 | -1): void {
  const next = direction > 0
    ? STEPS.find((s) => s > zoom.value + 0.001)
    : [...STEPS].reverse().find((s) => s < zoom.value - 0.001)
  if (next !== undefined) set(next)
}
</script>

<template>
  <div v-if="bridge" class="dev-zoom" role="group" aria-label="Zoom">
    <button type="button" aria-label="Zoom out" :disabled="zoom <= STEPS[0]" @click="step(-1)">−</button>
    <button type="button" class="dev-zoom__value" title="Actual size" @click="set(1)">{{ Math.round(zoom * 100) }}%</button>
    <button type="button" aria-label="Zoom in" :disabled="zoom >= STEPS[STEPS.length - 1]" @click="step(1)">+</button>
  </div>
</template>

<style>
.dev-zoom {
  position: fixed;
  right: 340px;
  bottom: 16px;
  z-index: 300;
  display: flex;
  height: 32px;
  box-sizing: border-box;
  overflow: hidden;
  border: 1px solid rgb(45 48 54 / 18%);
  border-radius: 6px;
  background: rgb(255 255 255 / 92%);
  box-shadow: 0 2px 8px rgb(0 0 0 / 8%);
}
.dev-zoom button {
  min-width: 30px;
  padding: 0 8px;
  border: 0;
  background: transparent;
  color: rgb(45 48 54 / 72%);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.dev-zoom .dev-zoom__value { min-width: 48px; font-variant-numeric: tabular-nums; }
.dev-zoom button:hover:not(:disabled) { background: rgb(45 48 54 / 7%); }
.dev-zoom button:disabled { color: rgb(45 48 54 / 28%); cursor: default; }
</style>
