/* The board: the seven dated columns on a plain .card-stack wearing
   .pattern-vertical-board, the spans in its place while a goal moves, the iridescent overlay and the drag's flying copy.
   The horizontal wheel listener lives here; the drag's listeners live in the shell. */
import { boardKeyTarget } from '../lib/keyboard'
import { computed, onBeforeUnmount, onMounted, ref, watch } from '../reactivity'
import { KButton, KCardStack } from '../kit'
import { Column } from './Column'
import { DragOverlay } from './DragOverlay'
import { SpansBoard } from './SpansBoard'
import { openSpans, spans, type SpanScale } from '../lib/spans'
import { store, todayIso } from '../store'
import { wheelIntent } from '../lib/boardWheel'
import { adjacentPeriodAnchor, type AdjustableVertical, type PeriodDirection } from '../lib/periodNavigation'
import type { BoardColumnData } from '../types'
import { mountIridescentOverlay } from '../kit-ext/iridescent'
import { devDeck } from '../lib/devDeck'
import { commandFilter, filterColumns, nothingFound } from '../lib/commandFilter'
import { bindRef, cx, sx } from '../bind'
import { tracked } from '../tracked'
import { useSetup, withDefaults } from '../setup'
import './board.css'

interface Props {
  columns: BoardColumnData[]
  showSampleBanner?: boolean
  onRemoveSample?: () => void
}
const DEFAULTS = { showSampleBanner: false }

export const Board = tracked(function Board(raw: Props) {
  const props = withDefaults(raw, DEFAULTS)
  const s = useSetup(props, (props) => {
    const boardRoot = ref<HTMLElement | null>(null)
    const iridescentCanvas = ref<HTMLCanvasElement | null>(null)
    let unmountIridescentOverlay: (() => void) | null = null
    watch(
      [boardRoot, iridescentCanvas],
      ([element, canvas]) => {
        unmountIridescentOverlay?.()
        unmountIridescentOverlay = null
        if (element instanceof HTMLElement && canvas) unmountIridescentOverlay = mountIridescentOverlay(element, canvas)
      },
      { flush: 'post' },
    )
    onBeforeUnmount(() => unmountIridescentOverlay?.())

    // Ruling 1: the board draws the seven dated columns; the Maybe bucket is the Inbox's.
    const dated = computed(() => filterColumns(props.columns).filter((c) => c.vertical !== 'maybe'))

    // Hover is a transient deck preview; an opened card's column owns the main role, Day while nothing is open.
    const deckActiveVertical = ref('day')
    const focusedVertical = ref<string | null>(null)
    const mainVertical = computed(() => focusedVertical.value ?? (
      store.state.openGoalId !== null && store.state.openGoalVertical ? store.state.openGoalVertical : 'day'
    ))
    watch(() => store.state.openGoalId, (id) => {
      if (id === null) deckActiveVertical.value = 'day'
    })
    function previewColumn(vertical: string) {
      if (store.state.openGoalId !== null || vertical === mainVertical.value) return
      deckActiveVertical.value = vertical
    }
    const deckStyle = computed(() => ({
      '--deck-day-width': devDeck.dayWidth > 0 ? `${devDeck.dayWidth}px` : 'auto',
      '--deck-active-gap-left': `${devDeck.activeGapLeft}px`,
      '--deck-active-gap-right': `${devDeck.activeGapRight}px`,
      '--deck-card-width': `clamp(8rem, ${devDeck.width}vw, 19rem)`,
      '--deck-card-overlap': `calc(-1 * clamp(0rem, ${devDeck.overlap}vw, 17.5rem))`,
      '--deck-card-perspective': `${devDeck.perspective}px`,
      '--deck-card-rotate-y': `${devDeck.rotateY}deg`,
      '--deck-card-rotate-x': `${devDeck.rotateX}deg`,
      '--deck-card-scale': String(devDeck.scale / 100),
      '--deck-card-active-rotate-y': `${devDeck.activeRotateY}deg`,
      '--deck-card-active-scale': String(devDeck.activeScale / 100),
      '--deck-card-offset-y': `${devDeck.offsetY}px`,
      '--deck-card-active-offset-y': `${devDeck.activeOffsetY}px`,
    }))

    const periodDirection = ref<PeriodDirection>(1)
    const periodSwapId = ref(0)
    async function loadPeriod(anchor: string, direction: PeriodDirection) {
      periodDirection.value = direction
      // In the board's own tick: a column must still hold its old period when the swap starts.
      await store.loadBoard(anchor, () => { periodSwapId.value += 1 })
    }
    function navigatePeriod(vertical: string, direction: PeriodDirection) {
      const anchor = store.state.board?.anchor_date
      if (!anchor) return
      void loadPeriod(adjacentPeriodAnchor(anchor, vertical as AdjustableVertical, direction), direction)
    }
    /* The single bar a column away from today returns every column to the period that holds today. */
    function navigateToday() {
      const today = todayIso()
      const current = store.state.board?.anchor_date
      if (!current || current === today) return
      void loadPeriod(today, current < today ? 1 : -1)
    }
    /** The middle bar of a column's sign opens that column's spans, starting at this period. */
    function openMode(vertical: string, periodKey: string | null) {
      if (spans.vertical) return
      void openSpans(vertical as SpanScale, vertical, periodKey, todayIso())
    }

    function onFocus(event: React.FocusEvent) {
      if (!boardKeyTarget(event.target)) return
      focusedVertical.value = (event.target as HTMLElement).closest<HTMLElement>('[data-keyboard-column]')?.dataset.vertical ?? null
    }
    /* Capture phase, non-passive: the column boxes between the pointer and the strip are overflow:hidden scroll
       containers, so by the time a horizontal delta bubbles it has already been eaten (lib/boardWheel.ts). */
    function onWindowWheel(event: WheelEvent) {
      const target = event.target instanceof Element ? event.target : null
      const strip = target?.closest<HTMLElement>('.pattern-vertical-board')
      if (!strip) return
      const intent = wheelIntent(event.deltaX, event.deltaY, strip.scrollLeft, strip.scrollWidth, strip.clientWidth)
      if (!intent) return
      strip.scrollLeft += intent.scrollBy
      event.preventDefault()
    }
    onMounted(() => {
      window.addEventListener('wheel', onWindowWheel, { capture: true, passive: false })
    })
    onBeforeUnmount(() => {
      window.removeEventListener('wheel', onWindowWheel, { capture: true })
    })

    /* Selection stays available at rest and on press, then locks from arm through settle; on body, since the gesture can
       start over any card in any column. */
    const isDragging = computed(() => store.state.drag.id !== null || store.state.drag.settling !== null)
    watch(isDragging, (dragging) => {
      document.body.classList.toggle('pattern-vertical-board__no-select', dragging)
    })
    onBeforeUnmount(() => document.body.classList.remove('pattern-vertical-board__no-select'))

    return {
      boardRoot, iridescentCanvas, dated, deckActiveVertical, mainVertical, previewColumn, deckStyle, periodDirection, periodSwapId,
      navigatePeriod, navigateToday, openMode, onFocus,
    }
  })

  const dated = s.dated.value
  const mainVertical = s.mainVertical.value
  return (
    <>
      {props.showSampleBanner ? (
        <div className="pattern-vertical-board__banner" data-cap="sample-banner">
          <p className="t-body">This is sample data, here to show how the board works.</p>
          <KButton data-cap="remove-sample" onClick={() => props.onRemoveSample?.()}>Remove sample data</KButton>
        </div>
      ) : null}
      {store.state.loading && !dated.length ? (
        <div className="pattern-vertical-board__spinner" role="status" aria-label="Loading"></div>
      ) : null}
      {spans.vertical && !commandFilter.text ? <SpansBoard /> : null}
      {dated.length && (!spans.vertical || commandFilter.text) ? (
        <KCardStack
          ref={bindRef(s.boardRoot)}
          className={cx('pattern-vertical-board', {
            _loading: store.state.loading,
            'pattern-vertical-board--flat': !devDeck.use3D,
            'pattern-vertical-board--family': store.familyLight.value !== null,
            'pattern-vertical-board--light-fast': store.state.lightFast,
            'pattern-vertical-board--nothing-found': nothingFound.value,
          })}
          style={sx(s.deckStyle.value)}
          onFocusCapture={s.onFocus}
          data-role="column-strip"
        >
          {dated.map((column) => (
            <Column
              key={column.vertical}
              vertical={column.vertical}
              title={column.title}
              subLabel={column.subLabel}
              shorter={column.shorter}
              label={column.label}
              active={column.active}
              deckMain={mainVertical === column.vertical}
              deckActive={store.state.openGoalId === null && column.vertical !== mainVertical
                && s.deckActiveVertical.value === column.vertical}
              addPlaceholder={column.addPlaceholder}
              goals={column.goals}
              periodKey={column.periodKey}
              away={column.away}
              periodDirection={s.periodDirection.value}
              periodSwapId={s.periodSwapId.value}
              onMouseEnter={() => s.previewColumn(column.vertical)}
              onPointerMove={() => s.previewColumn(column.vertical)}
              onPeriodStep={s.navigatePeriod}
              onPeriodToday={s.navigateToday}
              onPeriodMode={s.openMode}
            />
          ))}
        </KCardStack>
      ) : null}
      <canvas ref={bindRef(s.iridescentCanvas)} data-role="iridescent-overlay" aria-hidden="true" hidden></canvas>
      <DragOverlay />
    </>
  )
})
