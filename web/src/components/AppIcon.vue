<script setup lang="ts">
/** The one place Tabler enters this codebase. Business components say
 *  `<AppIcon name="tag" />` and never import from `@tabler/icons-vue` themselves — the
 *  explicit registry below is what keeps the bundle tree-shakeable (named imports only,
 *  no wildcard) and keeps icon choice a single-file decision. Icons inherit
 *  `currentColor` (Tabler's own default) so existing CSS color rules keep working.
 *  Decorative by default: without a `label` the svg is `aria-hidden`. */
import { computed } from 'vue'
import '../lib/devIcons'
import {
  IconArrowLeft,
  IconArrowRight,
  IconCalendar,
  IconChevronDown,
  IconChevronLeft,
  IconChevronRight,
  IconDots,
  IconFile,
  IconFolder,
  IconHierarchy,
  IconHistory,
  IconInbox,
  IconListDetails,
  IconMessageCircle,
  IconPlus,
  IconPointFilled,
  IconRotateClockwise,
  IconSearch,
  IconTag,
  IconTrash,
  IconX,
} from '@tabler/icons-vue'

const REGISTRY = {
  'arrow-left': IconArrowLeft,
  'arrow-right': IconArrowRight,
  calendar: IconCalendar,
  comment: IconMessageCircle,
  'chevron-down': IconChevronDown,
  'chevron-left': IconChevronLeft,
  'chevron-right': IconChevronRight,
  today: IconPointFilled,
  dots: IconDots,
  file: IconFile,
  folder: IconFolder,
  hierarchy: IconHierarchy,
  history: IconHistory,
  inbox: IconInbox,
  plus: IconPlus,
  repeat: IconRotateClockwise,
  search: IconSearch,
  subtask: IconListDetails,
  tag: IconTag,
  trash: IconTrash,
  x: IconX,
} as const

const props = withDefaults(defineProps<{
  name: keyof typeof REGISTRY
  size?: number
  stroke?: number
  /** Accessible name. Omit for decorative icons — they render `aria-hidden`. */
  label?: string
}>(), {
  size: 18,
  stroke: 2.2,
  label: undefined,
})

const icon = computed(() => REGISTRY[props.name])
const BASE_NAMES = new Set<keyof typeof REGISTRY>([
  'calendar', 'comment', 'file', 'folder', 'hierarchy', 'history', 'inbox', 'plus', 'repeat', 'subtask', 'tag', 'trash',
])
const ARROW_NAMES = new Set<keyof typeof REGISTRY>([
  'arrow-left', 'arrow-right', 'chevron-down', 'chevron-left', 'chevron-right', 'today',
])
const tuningClass = computed(() => {
  if (BASE_NAMES.has(props.name)) return 'app-icon--base'
  if (ARROW_NAMES.has(props.name)) return 'app-icon--arrows'
  if (props.name === 'search') return 'app-icon--search'
  if (props.name === 'dots') return 'app-icon--menu'
  return undefined
})
</script>

<template>
  <component
    :is="icon"
    :size="props.size"
    :stroke-width="props.stroke"
    class="app-icon"
    :class="tuningClass"
    :aria-hidden="props.label ? undefined : 'true'"
    :aria-label="props.label"
    :role="props.label ? 'img' : undefined"
  />
</template>

<style>
.app-icon { display: block; flex: 0 0 auto; }
.app-icon.app-icon--base,
.app-icon.app-icon--arrows,
.app-icon.app-icon--search,
.app-icon.app-icon--menu { max-width: none !important; }
.app-icon.app-icon--base { width: var(--app-icon-size-base, 16px) !important; height: var(--app-icon-size-base, 16px) !important; }
.app-icon.app-icon--arrows { width: var(--app-icon-size-arrows, 14px) !important; height: var(--app-icon-size-arrows, 14px) !important; }
.app-icon.app-icon--search { width: var(--app-icon-size-search, 24px) !important; height: var(--app-icon-size-search, 24px) !important; }
.app-icon.app-icon--menu {
  width: var(--app-icon-size-menu, 16px) !important;
  height: var(--app-icon-size-menu, 16px) !important;
  fill: none !important;
  stroke-width: var(--app-icon-stroke-menu, 2.2) !important;
}
</style>
