<script setup lang="ts">
// A desk's head (the Inbox, Documents; Inbox and Documents redesign, round 9): its title, the board's column headline,
// kept at the top while the desk scrolls, the desk fading out under it with no band; at the right, × goes back to the
// board, as Esc and the place's tag do. Whatever the desk adds beside its title (Documents' +) comes in the slot.
import AppIcon from './AppIcon.vue'
import { store } from '../store'

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

<style>
/* Sticky in the desk's own scroll: the desk's grey down to 60 px, fading out by 96 px, so what scrolls under it goes out of
   sight without a line. The title is the board's own column headline (`.t-title` at 31/40). */
.desk-head { position: sticky; top: 0; z-index: 5; display: flex; align-items: flex-start; gap: 10px; box-sizing: border-box; height: 96px;
  margin: 0 -46px; padding: 18px 46px 0 22px; pointer-events: none;
  background: linear-gradient(#f5f5f7 0, #f5f5f7 60px, rgb(245 245 247 / 0) 96px); }
.desk-head > * { pointer-events: auto; }
.desk-head__title.t-title { margin: 0; font-size: 31px; line-height: 40px; }
/* The app's window ×: a 16 px x in a 32 px round button, 55 % black (WindowStack.vue). */
.desk-head__close { position: absolute; top: 22px; right: 22px; display: grid; place-items: center; width: 32px; height: 32px; padding: 0; border: 0;
  border-radius: 16px; background: transparent; color: rgb(0 0 0 / 55%); cursor: pointer; }
.desk-head__close:hover { background: rgb(0 0 0 / 6%); color: #000; }
</style>
