/* A column's carried-over plans: one group on top, on a faint ground, one line of
   notice ("8 from Sep"), "Replan" with its black circle, the newest three and "N more". Pointing at a goal whose family
   has plans here, the box takes that goal's colour and shows its family's plans, and its height follows them; what it
   shows, how long it keeps it and where its height goes is `lib/carriedFilter.ts`. */
import type { MouseEvent as ReactMouseEvent } from 'react'
import { computed, ref } from '../reactivity'
import { KCardStack } from '../kit'
import { GoalCard } from './GoalCard'
import { AppIcon } from './AppIcon'
import { CarriedMascot, type CarriedMascotApi } from './CarriedMascot'
import { store, todayIso } from '../store'
import { MONTH_NAMES } from '../lib/periods'
import { useCarriedFilter } from '../lib/carriedFilter'
import { useCarriedPills, type CarriedPillsApi } from '../lib/carriedPills'
import { CarriedPills } from './CarriedPills'
import type { GoalCardData } from '../types'
import { bindRef, cx, fallthrough, sx } from '../bind'
import { tracked } from '../tracked'
import { listen, useSetup } from '../setup'
import './carriedGroup.css'

interface Props {
  vertical: string
  /** The period the column shows: "This week" keeps a plan in it (lib/carriedPills.ts). */
  periodKey?: string | null
  goals: GoalCardData[]
  onReplan?: (from: Element, plans: { id: string; title: string }[]) => void
}

function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export const CarriedGroup = tracked(function CarriedGroup(raw: Props & Record<string, unknown>) {
  const { vertical, periodKey, goals, onReplan, ...attrs } = raw
  const s = useSetup({ vertical, periodKey, goals, onReplan }, (props) => {
    /** The start of the period before the current one, for the column's scale. */
    const previous = computed(() => {
      const today = new Date(`${todayIso()}T12:00:00`)
      const d = new Date(today)
      switch (props.vertical) {
        case 'day': d.setDate(d.getDate() - 1); return { from: isoDay(d), to: isoDay(today) }
        case 'week': {
          const monday = new Date(today); monday.setDate(today.getDate() - ((today.getDay() + 6) % 7))
          const before = new Date(monday); before.setDate(monday.getDate() - 7)
          return { from: isoDay(before), to: isoDay(monday) }
        }
        case 'month': {
          const first = new Date(today.getFullYear(), today.getMonth(), 1, 12)
          return { from: isoDay(new Date(today.getFullYear(), today.getMonth() - 1, 1, 12)), to: isoDay(first) }
        }
        case 'quarter': {
          const q = Math.floor(today.getMonth() / 3)
          return { from: isoDay(new Date(today.getFullYear(), (q - 1) * 3, 1, 12)), to: isoDay(new Date(today.getFullYear(), q * 3, 1, 12)) }
        }
        default:
          return { from: `${today.getFullYear() - 1}-01-01`, to: `${today.getFullYear()}-01-01` }
      }
    })

    /** "8 from Sep": how many, and from when. "From last week" when every plan is from the period just before, "From
     *  earlier weeks" otherwise; the month is three letters so the line fits a narrow column. */
    const notice = computed(() => {
      const { from, to } = previous.value
      const one = props.goals.every((g) => (g.anchorDate ?? '') >= from && (g.anchorDate ?? '') < to)
      const last = new Date(`${from}T12:00:00`)
      const words: Record<string, [string, string]> = {
        day: ['yesterday', 'earlier days'],
        week: ['last week', 'earlier weeks'],
        month: [MONTH_NAMES[last.getMonth()]!.slice(0, 3), 'earlier months'],
        quarter: [`Q${Math.floor(last.getMonth() / 3) + 1}`, 'earlier quarters'],
        year: [`${last.getFullYear()}`, 'earlier years'],
      }
      const [single, several] = words[props.vertical] ?? ['earlier', 'earlier']
      return `${props.goals.length} from ${one ? single : several}`
    })

    const newestFirst = computed(() => [...props.goals].sort((a, b) => (b.anchorDate ?? '').localeCompare(a.anchorDate ?? '')))

    /* The box is the tinted piece. While a goal under it is pointed at, the place around it keeps its height and the box
       fills it; the room the filter leaves inside the box is the mascot's. */
    const root = ref<HTMLElement | null>(null)
    const place = ref<HTMLElement | null>(null)
    // The mascot: its root element and what it exposes.
    const mascotEl = ref<HTMLElement | null>(null)
    const mascot = ref<CarriedMascotApi | null>(null)
    let pills: CarriedPillsApi | null = null // made below: it takes the box's own pointer in and out
    const { hold, pinned, gap, circle, lift, lit, visible, family, button, opened, more: onMore, openPlan, enter, leave } = useCarriedFilter({
      vertical: () => props.vertical,
      plans: () => newestFirst.value,
      box: root,
      place,
      room: () => {
        const m = mascot.value
        const el = mascotEl.value
        return m && el ? { el, need: m.need() } : null
      },
      held: () => (pills?.waiting.value ? pills.tone.value : null),
    })
    /* The pills beside a pointed plan (docs/design/carried-pills.md) are drawn outside the box, and are the box's: moving
       onto them is not leaving it. */
    pills = useCarriedPills({
      vertical: () => props.vertical,
      periodKey: () => props.periodKey ?? null,
      plans: () => props.goals,
      box: root,
      open: () => openPlan.value !== null,
      enter,
      leave,
    })
    // Native listeners: a goal's menu teleported out of the box is outside it in the DOM.
    listen(root, 'pointerenter', enter)
    const own = pills
    listen(root, 'pointerleave', (event) => {
      if (own.owns(event.relatedTarget)) return
      own.away()
      leave()
    })
    listen(root, 'pointerover', own.over)

    /** What the mascot says: why the box is emptier than it was. The count line above it already says where the plans
     *  come from. It speaks only when that is all of the story: the goal has nothing here, or the box shows everything
     *  it has. */
    const words = computed(() => {
      const plans = family.value
      if (!plans) return null
      if (!plans.length) return 'No due plans for this goal'
      return visible.value.length === plans.length ? "That's all for this goal" : null
    })

    /** A plan is open: the header line is the way back, anywhere on it but "Replan". */
    function onHeadClick(event: ReactMouseEvent): void {
      if (openPlan.value && !(event.target as Element).closest('[data-role="replan"]')) store.closeGoal()
    }

    function cardProps(goal: GoalCardData) {
      return {
        id: goal.id, parentId: goal.parentId, title: goal.title, done: goal.done, color: goal.color, vertical: goal.vertical,
        columnVertical: props.vertical, ghost: true, children: goal.children, repeat: goal.repeat,
      }
    }
    return {
      notice, root, place, mascotEl, mascot, hold, pinned, gap, circle, lift, lit, visible, button, opened, onMore, openPlan,
      words, onHeadClick, cardProps, pills: own,
    }
  })
  const openPlan = s.openPlan.value
  const hold = s.hold.value
  const lit = s.lit.value
  const button = s.button.value
  return (
    <div
      {...fallthrough({
        ref: bindRef(s.place),
        className: 'carried-place',
        'data-role': 'carried-place',
        style: sx({ minHeight: hold && !openPlan ? `${hold}px` : undefined }),
      }, attrs)}
    >
      <section
        ref={bindRef(s.root)}
        className={cx('carried-group', {
          'carried-group--lit': !!lit,
          'carried-group--lifted': s.pinned.value && !openPlan,
          'carried-group--open': !!openPlan,
        })}
        data-role="carried-group"
        data-count={goals.length}
        style={sx({ ...(lit ?? {}), '--carried-lift': s.lift.value ?? undefined })}
      >
        <div className="carried-group__head" onClick={s.onHeadClick}>
          <span className="carried-group__notice" data-role="carried-notice">{s.notice.value}</span>
          <button type="button" className="carried-group__replan" data-role="replan"
            onClick={(event) => onReplan?.(event.currentTarget, goals.map((g) => ({ id: g.id, title: g.title })))}>
            {' Replan'}<span className="carried-group__dot" aria-hidden="true"></span>
          </button>
        </div>
        <KCardStack dense data-section="carried">
          {s.visible.value.map((goal) => <GoalCard key={goal.id} {...s.cardProps(goal)} />)}
        </KCardStack>
        <CarriedMascot ref={bindRef(s.mascotEl)} expose={s.mascot} on={s.gap.value && !openPlan && s.words.value !== null}
          words={s.words.value} circle={s.circle.value} />
        {button ? (
          <button type="button" className="carried-group__more" data-role="carried-more" onClick={() => s.onMore()}>
            {button}<AppIcon name="chevron-down" size={12} className={cx({ 'carried-group__chevron--open': s.opened.value })} />
          </button>
        ) : null}
        <CarriedPills api={s.pills} />
      </section>
    </div>
  )
})
