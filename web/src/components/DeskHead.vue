<script setup lang="ts">
// A desk's head (the Inbox, Documents; Inbox and Documents redesign, round 9): its title, the board's column headline,
// kept at the top while the desk scrolls, the desk fading out under it with no band; at the right, × goes back to the
// board, as Esc and the place's tag do. Whatever the desk adds beside its title (Documents' +) comes in the slot.
import AppIcon from './AppIcon.vue'
import { store } from '../store'
import './deskHead.css'

defineProps<{ title: string }>()
</script>

<template>
  <header class="desk-head" data-role="desk-head">
    <h1 class="t-title desk-head__title">{{ title }}</h1>
    <slot />
    <button type="button" class="desk-head__close" data-role="desk-close" :aria-label="`Close ${title}`" @click="store.setView('verticals')">
      <AppIcon name="x" :size="16" />
    </button>
  </header>
</template>
