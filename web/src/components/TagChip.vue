<script setup lang="ts">
/* One pressable tag (S-125). Built on the kit's KChip, not KTag: the canon doc's own distinction
   is the reason — "Tag stays metadata, button commits an outcome, chip picks"
   (design-system/skills/kk-design-system/canon/components.md, "Chip"). `KTag` takes no click at
   all ("one default slot, no emits"); this element must be clickable (S-125 step 2: "click a
   `#retro` tag chip"), so `KChip` is the correct primitive, standalone (outside a `KChipWrap`,
   so it reads its own `pressed` prop directly instead of a group's v-model).

   The `#` is CSS, never data (`docs/UI_REFERENCE.md` §3: "The `#` is CSS, not data. The tag value
   stored is bare... This matters for the retro query" — S-125's own assert repeats it: "the
   chip's rendered text is `#retro` and the stored tag is `retro`"). `tag` here is always bare;
   `data-tag` carries the same bare value for tests, since `KChip`'s own `value` prop is consumed
   internally and is not reflected onto the DOM. */
import { KChip } from '@konstantinopolskii/vue'

withDefaults(defineProps<{ tag: string; pressed?: boolean }>(), { pressed: false })
const emit = defineEmits<{ select: [tag: string] }>()
</script>

<template>
  <KChip class="tag-chip" :value="tag" :pressed="pressed" :data-tag="tag" @click="emit('select', tag)">
    {{ tag }}
  </KChip>
</template>

<style>
/* docs/UI_REFERENCE.md §3's own rule, carried over verbatim (class name is new — this is not
   `.GoalRow-tag`, their class, but the same CSS mechanism). */
.tag-chip.tag-chip:before {
  content: '#';
  font-weight: 900;
  margin-right: 1px;
}
</style>
