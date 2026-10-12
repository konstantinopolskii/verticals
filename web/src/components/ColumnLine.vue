<script setup lang="ts">
// The line pinned at a column's top (docs/design/column-bars.md): when the column scrolls it stays at its top on white
// while the goals fade out under it over 14 px, and the period bars (ColumnBars.vue) stand on it. At the column's top it
// says the kind ("Week"), where the header's own kind stands; once the big name has scrolled under it, the period
// ("5–11 Oct"), in the same words the header chose for its room. The two words cross-fade where they stand.
//
// It is the first child of the slide that scrolls and sticks to its top, so it wheels, swaps and scrolls with the slide
// as the header does, and a wheel over it scrolls the column. It listens to that slide itself.
//
// It also says where its words end, so the left box of the sign at the column's right (ColumnBars.vue) can grow into
// the room they leave and no further: it never covers what a click on the line reads.
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { fontEpoch, fontOf, widthOf } from '../lib/fitName'
import './columnLine.css'

const props = defineProps<{
  /** The kind, as the header's kind row says it: "Week", "Week · Dec ’27". */
  kind: string
  /** The period, the form of the big name that fits, with what the kind line carried: "5–11 Oct", "Wed", "21–27 · Dec". */
  name: string
}>()

/* The big name stands on a baseline 55 px under the column's top, its descenders reach 61, and the line ends at 28. At 27
   px of scroll its caps are under the line, at 32 nearly all of its descenders: the period takes the kind's place then,
   with the name out of sight. Going back it is held down to 28, 4 px sooner than it came, so a column resting at the
   edge doesn't flicker between the two. */
const NAMED_AT = 32
const HOLD = 4
/** The fade under the line grows with the scroll over its own height, 14 px: at rest the big name stands right under
 *  the line and nothing fades. */
const FADE = 14

const emit = defineEmits<{
  /** Where the words end, in px from the column's left: the longer of the kind and the period, in their own type. */
  words: [end: number]
}>()

const line = ref<HTMLElement | null>(null)
const kindWord = ref<HTMLElement | null>(null)
const nameWord = ref<HTMLElement | null>(null)
const named = ref(false)
let slide: HTMLElement | null = null

/** The words stand 14 px in from the column's left (`.column-line__words`). A canvas measures them, as the header's fit
 *  does (`lib/fitName.ts`), and again when a font arrives. */
const WORDS_LEFT = 14
function reachWords(): void {
  if (!kindWord.value || !nameWord.value) return
  const kind = widthOf(props.kind, fontOf(kindWord.value))
  const name = widthOf(props.name, fontOf(nameWord.value))
  emit('words', WORDS_LEFT + Math.max(kind, name))
}
watch([() => props.kind, () => props.name, fontEpoch], reachWords)

/** The slide has scrolled to `top`. The fade follows it on the line itself, a frame at a time and without a render; the
 *  words change only at the thresholds. */
function scrolled(): void {
  if (!slide) return
  const top = slide.scrollTop
  line.value?.style.setProperty('--line-fade', String(Math.min(1, Math.max(0, top / FADE))))
  const now = top >= (named.value ? NAMED_AT - HOLD : NAMED_AT)
  if (now !== named.value) named.value = now
}
onMounted(() => {
  slide = line.value?.parentElement ?? null
  slide?.addEventListener('scroll', scrolled, { passive: true })
  scrolled()
  reachWords()
})
onBeforeUnmount(() => slide?.removeEventListener('scroll', scrolled))
</script>

<template>
  <!-- A click on the line's words is a click on the header they cover (Column.vue). -->
  <div ref="line" class="column-line" data-role="column-line" :data-state="named ? 'period' : 'kind'">
    <div class="column-line__words">
      <p ref="kindWord" class="column-line__kind" data-role="column-line-kind" aria-hidden="true">{{ kind }}</p>
      <p ref="nameWord" class="column-line__name" data-role="column-line-name" aria-hidden="true">{{ name }}</p>
    </div>
  </div>
</template>
