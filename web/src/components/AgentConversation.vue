<script setup lang="ts">
// The conversation (docs/design-handoff S2.P1): a column of balloons over the board or a window, the agent's black on
// the left, yours a shade lighter on the right, rising out of the circle and sinking back into it. Its links move the
// app in place; an ask of the agent's is its balloon with the choices as buttons. The goals and documents a message links
// stand under its words as chips (AgentChips.vue; docs/design/agent-chips.md).
import { computed, nextTick, ref, watch } from 'vue'
import AgentChips from './AgentChips.vue'
import AnswerUndo from './AnswerUndo.vue'
import { chipLinks, withoutChipLines } from '../lib/chipLinks'
import { agentChat, agentOf, balloons, decide } from '../lib/agentChat'
import { askDetail } from '../lib/askDetail'
import { chatMarkdown } from '../lib/chatMarkdown'
import { scrollLook, useMessageScroll } from '../lib/messageScroll'
import { flight, land } from '../lib/chatFlight'
import { curve, reducedMotion } from '../lib/motion'
import { windows } from '../lib/windows'
import './agentConversation.css'

const emit = defineEmits<{ link: [url: string, web: boolean, from: Element | null] }>()

const column = ref<HTMLElement | null>(null)
const content = ref<HTMLElement | null>(null)
/* The column runs the window's height and scrolls past its two lines, the top one 32 px down and the bottom one 12 px
   above the field, so a balloon less than half past a line shows whole instead of cut (S2.P5.009). */
function lines() {
  const el = column.value
  const style = el ? getComputedStyle(el) : null
  return { top: parseFloat(style?.paddingTop ?? '32'), bottom: innerHeight - parseFloat(style?.paddingBottom ?? '0') }
}
const { toEnd } = useMessageScroll(column, content, lines, () => balloons.value.length)
const agentName = computed(() => agentOf(agentChat.selection?.provider).label)
const look = computed(() => scrollLook())
/* What each ask will change: the goal and its date (lib/askDetail.ts; docs/design/agent-fixes.md, fix 6). */
const changes = computed(() => Object.fromEntries(balloons.value.map((balloon) => [balloon.key, balloon.ask ? askDetail(balloon.ask) : null])))
/* What each of the agent's messages made or changed, from the links in its words. */
const chips = computed(() => Object.fromEntries(balloons.value.map((balloon) => [balloon.key, balloon.who === 'agent' ? chipLinks(balloon.text) : []])))

watch(() => [agentChat.open, balloons.value.length, balloons.value[balloons.value.length - 1]?.text], async () => {
  if (!agentChat.open) return
  await nextTick()
  toEnd()
  arrive()
}, { flush: 'post' })

/* The answer going up from the circle opens the conversation with no reveal: the balloon itself is the movement. */
const transitionName = computed(() => (flight.value?.kind === 'reply' ? 'agent-conversation-reply' : 'agent-conversation'))

/* A balloon whose words flew in starts where they stood: yours from the field in 280 ms (S2.P3.019), the agent's from
   the circle in 300 ms after the press, the ones above it making room (S2.P4.016, .017). */
function arrive(): void {
  const all = content.value?.querySelectorAll<HTMLElement>('[data-balloon]')
  const last = all?.[all.length - 1]
  if (!all || !last) return
  const f = land(last.dataset.who === 'you' ? 'you' : 'agent')
  if (!f || reducedMotion()) return
  const box = last.getBoundingClientRect()
  const style = getComputedStyle(last)
  const dx = f.left - (box.left + parseFloat(style.paddingLeft))
  const dy = f.top - (box.top + parseFloat(style.paddingTop))
  const from = `translate(${dx}px, ${dy}px)`
  if (f.kind === 'sent') {
    last.animate([{ transform: from, backgroundColor: 'rgb(43 43 43 / 0)' }, { transform: 'none', backgroundColor: '#2b2b2b' }],
      { duration: 280, easing: curve('large') })
    return
  }
  const timing = { duration: 300, delay: 90, easing: curve('large'), fill: 'backwards' as const }
  last.animate([{ transform: from }, { transform: 'none' }], timing)
  const room = `translateY(${box.height + 10}px)`
  for (const balloon of Array.from(all).slice(-12, -1)) balloon.animate([{ transform: room }, { transform: 'none' }], timing)
}

/* A click beside the balloons is a click on what lies under the conversation: it goes back into the circle (S2.P1.011). */
function onColumnClick(event: MouseEvent): void {
  if (!(event.target as HTMLElement).closest('[data-balloon]')) agentChat.open = false
}
function onClick(event: MouseEvent): void {
  const link = (event.target as HTMLElement).closest<HTMLAnchorElement>('a[data-app-link], a[data-web-link]')
  if (!link) return
  event.preventDefault()
  emit('link', link.dataset.appLink ?? link.dataset.webLink ?? link.href, !link.dataset.appLink, link)
}
</script>

<template>
  <Transition :name="transitionName">
    <div v-if="agentChat.open" class="agent-conversation"
      :class="{ 'agent-conversation--working': agentChat.running, 'agent-conversation--over-window': windows.list.length }"
      data-role="agent-conversation" :style="look">
      <div ref="column" class="agent-conversation__column" role="log" @click="onColumnClick" aria-live="polite" :aria-label="`Conversation with ${agentName}`">
        <div ref="content" class="agent-conversation__talk" @click="onClick">
          <div
            v-for="balloon in balloons"
            :key="balloon.key"
            class="agent-balloon"
            :class="[`agent-balloon--${balloon.who}`, { 'agent-balloon--error': balloon.error }]"
            data-balloon
            data-side="in"
            :data-who="balloon.who"
            :aria-label="balloon.who === 'you' ? 'You' : agentName"
          >
            <div v-if="balloon.who === 'you'" class="agent-balloon__plain">{{ balloon.text }}</div>
            <!-- eslint-disable-next-line vue/no-v-html -- chatMarkdown escapes every byte of the source -->
            <div v-else-if="withoutChipLines(balloon.text)" class="agent-balloon__markdown" v-html="chatMarkdown(withoutChipLines(balloon.text))"></div>
            <AgentChips v-if="chips[balloon.key]!.length" class="agent-balloon__chips" :links="chips[balloon.key]!" />
            <!-- At the answer's end, under what it made (docs/design/agent-answer-undo.md, agent-chips.md). -->
            <AnswerUndo v-if="balloon.who === 'agent' && balloon.answer" :answer="balloon.answer" stays />
            <div v-if="balloon.ask" class="agent-balloon__ask" data-role="agent-ask">
              <p class="agent-balloon__ask-title" :class="{ 'agent-balloon__ask-title--changes': changes[balloon.key] }">{{ balloon.ask.title }}</p>
              <p v-if="changes[balloon.key]" class="agent-balloon__ask-changes" data-role="agent-ask-changes">{{ changes[balloon.key]!.goal }}<template v-if="changes[balloon.key]!.date"><span class="agent-balloon__ask-sep" aria-hidden="true"> · </span>{{ changes[balloon.key]!.date }}</template></p>
              <div class="agent-balloon__choices">
                <button
                  v-for="option in balloon.ask.options"
                  :key="option.value"
                  type="button"
                  class="agent-balloon__choice"
                  :class="{ 'is-chosen': balloon.ask.chosen === option.value }"
                  :disabled="balloon.ask.done"
                  @click="decide(balloon.ask.requestId, option.value)"
                >{{ option.label }}</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Transition>
</template>
