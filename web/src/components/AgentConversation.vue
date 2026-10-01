<script setup lang="ts">
// The conversation (docs/design-handoff S2.P1): a column of balloons over the board or a window, the agent's black on
// the left, yours a shade lighter on the right, rising out of the circle and sinking back into it. Its links move the
// app in place; an ask of the agent's is its balloon with the choices as buttons.
import { computed, nextTick, ref, watch } from 'vue'
import { agentChat, agentOf, balloons, decide } from '../lib/agentChat'
import { chatMarkdown } from '../lib/chatMarkdown'
import { scrollLook, useMessageScroll } from '../lib/messageScroll'

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

watch(() => [agentChat.open, balloons.value.length, balloons.value[balloons.value.length - 1]?.text], async () => {
  if (!agentChat.open) return
  await nextTick()
  toEnd()
}, { flush: 'post' })

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
  <Transition name="agent-conversation">
    <div v-if="agentChat.open" class="agent-conversation" :class="{ 'agent-conversation--working': agentChat.running }"
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
            <div v-else-if="balloon.text" class="agent-balloon__markdown" v-html="chatMarkdown(balloon.text)"></div>
            <div v-if="balloon.ask" class="agent-balloon__ask" data-role="agent-ask">
              <p class="agent-balloon__ask-title">{{ balloon.ask.title }}</p>
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

<style>
.agent-conversation {
  position: fixed;
  z-index: 290;
  left: 50%;
  top: 0;
  bottom: 0;
  width: min(562px, calc(100vw - 32px));
  transform: translateX(-50%);
  pointer-events: none;
}
/* While the agent works its step bubble stands where its next balloon will (S2.P3.005): the column makes room. */
.agent-conversation--working { --vt-conversation-lift: 46px; }
.agent-conversation__column {
  position: relative;
  box-sizing: border-box;
  height: 100%;
  padding: 32px 0 calc(24px + var(--vt-field-height, 84px) + 12px + max(var(--vt-conversation-lift, 0px), var(--vt-tags-lift, 0px)));
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: none;
  pointer-events: auto;
}
.agent-conversation__column::-webkit-scrollbar { display: none; }
.agent-conversation__talk { display: flex; flex-direction: column; justify-content: flex-end; gap: 10px; min-height: 100%; }
.agent-balloon {
  flex: none;
  box-sizing: border-box;
  border-radius: var(--vt-radius-balloon);
  color: #fff;
  font: 400 15px/22px var(--font-body);
  overflow-wrap: anywhere;
  user-select: text;
  transform-origin: 50% 100%;
  transition: opacity var(--gone-ms, 200ms) ease, filter var(--gone-ms, 200ms) ease, transform var(--gone-ms, 200ms) ease;
}
.agent-balloon--you { align-self: flex-end; max-width: 400px; padding: 12px 20px 13px; background: #2b2b2b; --turn: 1; --toward: -1; }
.agent-balloon--agent { align-self: flex-start; width: fit-content; max-width: 420px; padding: 14px 22px 15px; background: #000; --turn: -1; --toward: 1; }
.agent-balloon[data-side='top'] {
  opacity: 0;
  filter: blur(var(--gone-blur, 6px));
  transform: rotate(calc(var(--turn) * var(--gone-turn, 2deg))) scale(var(--gone-scale, .78));
}
.agent-balloon[data-side='bottom'] {
  opacity: 0;
  filter: blur(var(--gone-blur, 6px));
  transform: translate(calc(var(--toward) * var(--gone-x, 22px)), var(--gone-y, 14px)) rotate(calc(var(--turn) * var(--gone-turn, 2deg)))
    scale(var(--gone-scale, .78));
}
.agent-balloon--error { color: rgb(255 255 255 / 72%); }
.agent-balloon__plain { white-space: pre-wrap; }
.agent-balloon__markdown p, .agent-balloon__markdown ul, .agent-balloon__markdown ol, .agent-balloon__markdown pre,
.agent-balloon__markdown blockquote, .agent-balloon__markdown .chat-table { margin: 0 0 12px; }
.agent-balloon__markdown > :last-child { margin-bottom: 0; }
.agent-balloon__markdown ul, .agent-balloon__markdown ol { padding-left: 20px; }
.agent-balloon__markdown strong { font-weight: 600; }
.agent-balloon__markdown a { color: inherit; text-decoration: underline; text-decoration-thickness: 1px; text-underline-offset: .15em;
  text-decoration-color: rgb(255 255 255 / 40%); cursor: pointer; }
.agent-balloon__markdown code { font-size: 13px; }
.agent-balloon__markdown pre { overflow-x: auto; }
.agent-balloon__markdown blockquote { padding-left: 12px; border-left: 2px solid rgb(255 255 255 / 30%); }
.agent-balloon__markdown .chat-table { overflow-x: auto; }
.agent-balloon__markdown table { border-collapse: collapse; font-size: 13px; line-height: 18px; }
.agent-balloon__markdown th, .agent-balloon__markdown td { padding: 4px 12px 4px 0; text-align: left; vertical-align: top; }
.agent-balloon__markdown th { font-weight: 600; }
.agent-balloon__ask-title { margin: 0 0 10px; font-weight: 600; }
.agent-balloon__markdown + .agent-balloon__ask { margin-top: 12px; }
.agent-balloon__choices { display: flex; flex-wrap: wrap; gap: 8px; }
.agent-balloon__choice {
  height: 32px;
  padding: 0 14px;
  border: 0;
  border-radius: 16px;
  background: #fff;
  color: #000;
  font: 500 14px/20px var(--font-body);
  cursor: pointer;
}
.agent-balloon__choice:disabled { opacity: .4; cursor: default; }
.agent-balloon__choice.is-chosen { opacity: 1; }
.agent-balloon__choice:focus-visible { outline: 2px solid #fff; outline-offset: 2px; }
.agent-conversation-enter-active { transition: clip-path var(--vt-dur-rise) var(--vt-ease-large), opacity var(--vt-dur-rise) linear; }
.agent-conversation-leave-active { transition: clip-path var(--vt-dur-fade) var(--vt-ease-large), opacity var(--vt-dur-fade) linear; }
.agent-conversation-enter-from, .agent-conversation-leave-to { clip-path: inset(100% 0 0 0); opacity: 0; }
@media (prefers-reduced-motion: reduce) {
  .agent-conversation-enter-active, .agent-conversation-leave-active { transition: opacity var(--vt-crossfade) linear; }
  .agent-conversation-enter-from, .agent-conversation-leave-to { clip-path: none; }
  .agent-balloon[data-side='top'], .agent-balloon[data-side='bottom'] { filter: none; transform: none; }
  .agent-balloon { transition: opacity var(--vt-crossfade) linear; }
}
</style>
