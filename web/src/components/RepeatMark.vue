<script setup lang="ts">
import AppIcon from './AppIcon.vue'
import './repeatMark.css'

/* The recurrence mark glued to the last word of a card's title. Measured on the reference
   (P-29, 2026-08-10): 15 x 14 px, 8 px gap, `rgba(45,48,54,.3)`.

   Its own file rather than eleven more lines inside `GoalCard.vue`, which sits against
   ARCHITECTURE.md §2's 750-line module rule (S-90a) — a self-contained mark with no props and no
   state was the cleanest thing to lift out. */
</script>

<template>
  <AppIcon
    name="repeat"
    class="goal-card__repeat"
    data-role="repeat-indicator"
    label="Repeating goal"
  />
</template>
