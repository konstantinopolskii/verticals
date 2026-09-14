<script setup lang="ts">
/* J3 (docs/JOURNEYS.md): "park an idea without deciding" — the Maybe bucket
   (verticals/core/board.py MAYBE_KEY), reached from the nav's "Inbox" link instead of sitting
   inside the eight-column board strip. Same data `store.columns` already carries
   (`vertical === 'maybe'`), same Column/GoalCard/InlineAdd machinery every other bucket uses — no
   new fetch, no new capture semantics (`store.createGoalOn('maybe', title)`, wired through
   Column's own inline-add, is already exactly the right call for this vertical).

   Titled "Inbox", not the store's own "Maybe" (`lib/schedule.ts::columnTitle`) — the nav link
   that opens this view is spelled "Inbox" (docs/UI_MEASURED.md §7 Kept list;
   tools/uiref/render.mjs's navItems structural-drift assertion), and landing on a different word
   than the one just clicked would be a new inconsistency, not a neutral default. The board
   strip's own eighth column is untouched and still says "Maybe" (S-63's own scenario reads that
   title there).

   Reference-fixture note (tests/uidiff/reference/inbox.html — no numeric gate covers this
   surface; S-100/S-102 are board-only): the reference planner's own Inbox is a single centered white card
   with three header icon-buttons (email-in, add-goal, an options menu). None of the three has any
   basis in this repo's docs (ARCHITECTURE.md, JOURNEYS.md, ACCEPTANCE.md) — no "email into inbox"
   feature and no per-view options menu is specified anywhere — so none is built here. Rendering
   an unspecified affordance would be inventing UI ("copywriting/UI decisions not already recorded
   are KK's call," per this work package's own instructions). Flagged in the final report, not
   decided in code.

   WP-C (KK, 2026-08-25): "ABOVE the task list THERE SHOULD BE LIKE A DOCUMENT OPENED BY DEFAULT,
   EXACTLY THE ONE THAT WE SAVE TO THE DOC SECTION AUTOMATICALLY" — `InboxDayDoc.vue` (own header
   comment carries the full brief and the design calls) now sits above the Maybe column inside a
   new `.inbox-view__stack` wrapper; the column itself is unchanged (same Column/GoalCard/InlineAdd
   machinery, still full drag/add/open). */
import { computed } from 'vue'
import Column from './Column.vue'
import InboxDayDoc from './InboxDayDoc.vue'
import { store } from '../store'

const maybeColumn = computed(() => store.columns.value.find((c) => c.vertical === 'maybe'))
</script>

<template>
  <div class="inbox-view" data-cap="inbox">
    <div class="inbox-view__stack">
      <InboxDayDoc />
      <Column
        v-if="maybeColumn"
        class="inbox-view__column"
        vertical="maybe"
        title="Inbox"
        :add-placeholder="maybeColumn.addPlaceholder"
        :goals="maybeColumn.goals"
      />
    </div>
  </div>
</template>

<style>
/* Global, matching every other product-side component's own convention (GoalCard.vue,
   SchedulePopover.vue, Board.vue) — new classes only. `.inbox-view__column` is a doubled-class
   override of the same kind Board.vue's own header comment names for `.goal-card.goal-card` /
   `.schedule-popover__stepper-label.schedule-popover__stepper-label`: the A7 kit rule
   (`.pattern-vertical-board__column { flex: 1 0 14.6%; ... max-width: 400px }`,
   design-system/style.css) only means anything as a flex item inside `.pattern-vertical-board`;
   standalone here it would still cap at that rule's own `max-width: 400px` (a bare `<div>` with
   `width: auto` fills its container, and `max-width` still applies outside a flex context) —
   narrower than wanted for a single full-width view. One class heavier wins regardless of
   stylesheet emission order, the same reasoning as both precedents above.

   Scroll model (KK bug report 2026-08-25, same day as WP-C shipped): the PAGE is the scrollport,
   nothing scrolls internally. WP-C's first cut kept the kit column's own `overflow-y: auto`
   scrollport and clipped the view (`overflow: hidden`) — fine for the short probe note the tests
   used, but a real day note (the first one is 3,900 characters) filled the viewport and nothing
   scrolled anywhere. This is a document page, not a board column: `.inbox-view` scrolls, the
   day doc and the Maybe list below it take their natural height, and the doubled-class override
   neutralizes the kit column's scrollport (`overflow-y: visible`) and its 400px width cap
   (`max-width: none` — the list shares the stack's 640px, matching the doc box above it). */
.inbox-view {
  height: 100%;
  min-width: 0;
  overflow-y: auto;
  padding: var(--space-6) var(--space-4);
  box-sizing: border-box;
}
.inbox-view__stack {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  min-width: 0;
  max-width: 640px;
  width: 100%;
  margin: 0 auto;
}
.inbox-view__column.inbox-view__column {
  min-width: 0;
  max-width: none;
  overflow-y: visible;
  max-height: none;
}
</style>
