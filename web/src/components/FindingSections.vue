<script setup lang="ts">
// What a column shows while you type (docs/design-handoff S1.P3): "Nothing today." when its period has no match, then
// the matches of other periods under small grey headlines; under the last column, the note when the server cut the list.
import { computed } from 'vue'
import { KCardStack } from '@konstantinopolskii/vue'
import GoalCard from './GoalCard.vue'
import { found, nothingIn, sectionsFor } from '../lib/finding'
import { commandFilter, serverMatches } from '../lib/commandFilter'
import { store } from '../store'
import type { GoalCardData } from '../types'

const props = defineProps<{
  vertical: string
  periodKey: string | null
  shown: GoalCardData[]
}>()

const onBoard = computed(() => {
  const ids = new Set<string>()
  const visit = (goals: GoalCardData[]) => { for (const goal of goals) { ids.add(goal.id); visit(goal.children ?? []) } }
  visit(props.shown)
  return ids
})
const sections = computed(() => serverMatches.value
  ? sectionsFor(props.vertical, props.periodKey, serverMatches.value, found.result?.parents ?? {}, onBoard.value)
  : [])
const planned = computed(() => props.shown.filter(goal => !goal.ghost))
const cut = computed(() => props.vertical === 'life' && !!serverMatches.value && !!found.result?.truncated)

/* A goal from another period opens where it lives: the words go and the board moves to it. Its square still ticks. */
function open(event: MouseEvent): void {
  const target = event.target as HTMLElement
  if (target.closest('[data-cap="complete"], [data-role="goal-actions-trigger"]')) return
  const id = target.closest<HTMLElement>('[data-goal-id]')?.dataset.goalId
  if (!id) return
  event.preventDefault()
  event.stopPropagation()
  commandFilter.text = ''
  void store.navigateToGoal(id)
}

function cardProps(goal: GoalCardData) {
  return {
    id: goal.id, parentId: goal.parentId, title: goal.title, done: goal.done, color: goal.color, vertical: goal.vertical,
    columnVertical: props.vertical, children: goal.children,
  }
}
</script>

<template>
  <div class="finding" data-role="finding">
    <p v-if="!planned.length" class="finding__note" data-role="finding-nothing">{{ nothingIn(vertical) }}</p>
    <section v-for="section in sections" :key="section.key" class="finding__period" :data-period-key="section.key"
      :data-when="section.coming ? 'coming' : 'closed'">
      <h3 class="finding__headline" data-role="finding-headline">{{ section.headline }}</h3>
      <KCardStack dense @click.capture="open">
        <GoalCard v-for="goal in section.goals" :key="goal.id" v-bind="cardProps(goal)" />
      </KCardStack>
    </section>
    <p v-if="cut" class="finding__note" data-role="finding-cut">The first 200 matches. Type more to narrow them.</p>
  </div>
</template>

<style>
/* Every small grey line stands on the goals' squares (S1.P3.041). */
.finding { position: relative; z-index: 2; padding: 0 var(--space-2) 0 0; }
.finding__note {
  margin: 0;
  padding: 6px 0 6px 17px;
  color: rgb(0 0 0 / 45%);
  font: 400 12px/19px var(--font-body);
  white-space: nowrap;
}
.finding__headline {
  margin: 14px 0 6px;
  padding: 0 8px 0 17px;
  color: rgb(45 48 54 / 52%);
  font: 400 12px/16px var(--font-body);
  white-space: nowrap;
}
.finding__note + .finding__period .finding__headline, .finding > .finding__period:first-child .finding__headline { margin-top: 8px; }
/* Nothing matches anywhere: the board turns off as going deeper turns off what isn't related (S1.P3.014); the notes stay. */
.pattern-vertical-board--nothing-found .pattern-vertical-board__body::after { opacity: 1; visibility: visible; transition: none; }
.pattern-vertical-board--nothing-found .period-slide > .pattern-vertical-board__header {
  opacity: var(--goal-off-opacity);
  filter: grayscale(var(--goal-off-grey));
}
</style>
