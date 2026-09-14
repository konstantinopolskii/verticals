<script setup lang="ts">
/* Deliberately NOT KCardHeading: that component wraps output in div.card__heading, which carries
   its own margin-top (--space-2) and left/right padding (--card-inset-x) — exactly what the A7
   kit commit replaced with .pattern-vertical-board__header{padding:24px 8px 0 12px} to hit the
   measured baseline offset. Using KCardHeading here would double up padding and throw off the
   probe. A7's own commit message says as much: reuse the kit's .t-title/.t-caption utilities
   directly, no new/reused component wrapper. */
withDefaults(defineProps<{
  title: string
  subLabel?: string
}>(), { subLabel: '' })

</script>

<template>
  <header class="pattern-vertical-board__header column-header">
    <div v-if="subLabel" class="column-header__period-row">
      <p class="t-caption column-header__sub-label">{{ subLabel }}</p>
    </div>
    <div class="column-header__title-row">
      <h3 class="t-title">{{ title }}</h3>
    </div>
  </header>
</template>

<style>
/* Period context sits above the headline. Keep both rows inside the compact header; the headline
   remains single-line and ellipsized so narrow columns do not push the board out of alignment. */
.column-header.column-header {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: 24px 40px;
  gap: 0;
  align-content: start;
  overflow: hidden;
}
.column-header__period-row,
.column-header__title-row {
  grid-column: 1;
}
.column-header__period-row {
  grid-row: 1;
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
  padding-right: 36px;
  overflow: hidden;
}
.column-header__sub-label {
  margin: 0;
  overflow: hidden;
  color: rgb(45 48 54 / 52%);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.column-header__title-row {
  grid-row: 2;
  display: block;
  width: 100%;
  position: relative;
  top: -6px;
}
.column-header__title-row > .t-title {
  display: block;
  width: 100%;
  min-width: 0;
  line-height: 40px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--color-text);
}
</style>
