<script setup lang="ts">
import { ref } from 'vue'
import './devZoomPanel.css'

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
