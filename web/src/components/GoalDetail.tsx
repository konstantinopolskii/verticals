/* The open goal's notes, at the end of its card after its steps: the body, read as
   Markdown and edited in place with optimistic local state and debounced PATCHes, then the goal's links and the line of
   documents that mention it. Lines that are one link to a document leave the notes for the links; long notes show ten
   lines and say what is left. GoalCard draws it inside `<Transition name="goal-notes">`: the root takes its ref and
   class. */
import { keyboardHelpOpen } from '../lib/keyboard'
import { Fragment } from 'react'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from '../reactivity'
import { GoalDetailEditor } from './GoalDetailEditor'
import { GoalLinks } from './GoalLinks'
import { store } from '../store'
import { internalLinkOf, renderBodyElement, serializeBodyElement } from '../lib/bodyMarkdown'
import { useCommentAnchoring } from '../lib/commentAnchoring'
import { onBeforeQuit } from '../lib/beforeQuit'
import { MONTH_NAMES } from '../lib/periods'
import { leaveRoom, roomFor } from '../lib/columnRoom'
import { contentTop, familyBlock, fitScroll, scrollerOf } from '../lib/columnFit'
import { familyMoving } from '../lib/familyMotion'
import { reducedMotion } from '../lib/motion'
import {
  handleBodyBeforeInput,
  handleBodyKeydown,
  handleBodyPaste,
  normalizeBodyInput,
  resetBodyHistory,
} from '../lib/bodyTextarea'
import { bindRef, cx, fallthrough, sx } from '../bind'
import { tracked } from '../tracked'
import { listen, useSetup } from '../setup'
import './goalDetail.css'

type DocItem = { key: string; id?: string; title: string; updated: string | null; open: () => void; from?: string; fromId?: string }

export const GoalDetail = tracked(function GoalDetail(attrs: Record<string, unknown>) {
  const s = useSetup({}, () => {
    const notes = (() => {
      const goal = computed(() => store.state.goalDetail)
      const loading = computed(() => store.state.goalDetailLoading)
      const OPEN_MS = 360 // `goalDetail.css`'s opening: the column scrolls in step with it

      // Closing is at once: the card's facts line, "Add…" and these notes fold away together in GoalCard's leave transitions.
      function requestClose() {
        if (store.state.openGoalId === null) return
        store.closeFamily()
      }

      // A goal in a window goes with its window: Esc and × there, never a press beside it.
      const inWindow = () => store.state.openGoalVertical === 'window'

      function onDetailKeydown(event: KeyboardEvent) {
        if (store.state.openGoalId === null || inWindow()) return
        const hosted = document.querySelector<HTMLElement>(
          '#dropdownPortal [data-popover-surface][data-state="open"]',
        )
        if (event.key === 'Escape') {
          if (hosted || store.state.drag.id !== null || store.state.drag.settling) return // Esc in a drag cancels only the drag
          event.preventDefault()
          store.goUp() // up one level; at the first level, close
        }
      }

      function onInlinePointerDown(event: PointerEvent) {
        if (keyboardHelpOpen.value) return
        if (store.state.openGoalId === null || inWindow()) return
        const target = event.target as HTMLElement | null
        if (!target) return
        // The comments panel, the open goal's steps and a view's tag over the circle are not a press outside: the panel
        // lives at App's level, and the tag closes the goal itself when its click changes the view.
        if (target.closest('#goal-detail, #dropdownPortal, [data-goal-id], [data-open-region], [data-role="comments-panel"], .circle-tag')) return
        requestClose()
      }

      onMounted(() => {
        document.addEventListener('keydown', onDetailKeydown)
        document.addEventListener('pointerdown', onInlinePointerDown)
        void nextTick(fitIntoView) // at the click, not once the notes have loaded
      })
      onBeforeUnmount(() => {
        document.removeEventListener('keydown', onDetailKeydown)
        document.removeEventListener('pointerdown', onInlinePointerDown)
        stopScroll()
        leaveRoom(rootEl.value?.closest<HTMLElement>('.pattern-vertical-board__body') ?? null)
      })

      const rootEl = ref<HTMLElement | null>(null)
      const editingBody = ref(false)
      const bodyDraft = ref('')
      const bodyInputEl = ref<HTMLElement | null>(null)
      const bodyExpanded = ref(false)
      const BODY_SAVE_DEBOUNCE_MS = 1_000
      const bodySaveTimers = new Map<string, { timer: number; body: string }>()
      let bodySessionStart = ''
      let bodySessionId: string | null = null
      let bodySessionPersisted = ''

      // Ten lines, then the rest behind "N more lines"; notes up to five lines longer show in full.
      const LINE_PX = 22
      const PREVIEW_LINES = 10
      const FOLD_AT_LEAST = 5
      const PREVIEW_PX = LINE_PX * PREVIEW_LINES
      const moreLines = ref(0)
      const folded = computed(() => moreLines.value > 0 && !bodyExpanded.value && !editingBody.value)
      const moreLabel = computed(() => `${moreLines.value} more ${moreLines.value === 1 ? 'line' : 'lines'}`)

      const anchoring = useCommentAnchoring({
        bodyEl: bodyInputEl,
        editing: editingBody,
        targetType: 'goal',
        targetId: () => goal.value?.id ?? null,
      })

      /** A paragraph that is one link to a document and nothing else is a document the agent linked: it leaves the notes
       *  for the links. A link inside a sentence stays a link. */
      const linkedDocs = ref<Array<{ path: string; title: string }>>([])
      function markDocumentLines(root: HTMLElement): void {
        const found: Array<{ path: string; title: string }> = []
        for (const block of root.children) {
          const link = block.tagName === 'P' && block.children.length === 1 ? block.firstElementChild : null
          const target = link instanceof HTMLAnchorElement ? internalLinkOf(link) : null
          const isDoc = target?.kind === 'doc' && block.textContent?.trim() === link?.textContent?.trim()
          block.classList.toggle('goal-detail__doc-line', isDoc)
          if (isDoc && target && !found.some((d) => d.path === target.target)) {
            found.push({ path: target.target, title: link?.textContent?.trim() || target.target })
          }
        }
        linkedDocs.value = found
      }

      function renderBody(root: HTMLElement, body: string): void {
        renderBodyElement(root, body)
        markDocumentLines(root)
      }

      function measureBodyLength(): void {
        void nextTick(() => {
          const el = bodyInputEl.value
          if (!el) return
          const extra = Math.round(el.scrollHeight / LINE_PX) - PREVIEW_LINES
          moreLines.value = extra >= FOLD_AT_LEAST ? extra : 0
          void nextTick(fitIntoView)
        })
      }

      function paintBody(body: string): void {
        void nextTick(() => {
          if (bodyInputEl.value && !editingBody.value) {
            renderBody(bodyInputEl.value, body)
            measureBodyLength()
            anchoring.paintHighlights()
          }
        })
      }

      function flushBodySave(id: string, keepalive = false): Promise<void> {
        const pending = bodySaveTimers.get(id)
        if (!pending) return Promise.resolve()
        window.clearTimeout(pending.timer)
        bodySaveTimers.delete(id)
        if (id === bodySessionId) bodySessionPersisted = pending.body
        return store.updateGoal(id, { body: pending.body }, keepalive)
      }

      function flushAllBodySaves(keepalive = false): Promise<void[]> {
        return Promise.all([...bodySaveTimers.keys()].map((id) => flushBodySave(id, keepalive)))
      }

      function onBodyVisibilityChange() {
        if (document.visibilityState === 'hidden') void flushAllBodySaves(true)
      }

      function onBodyPageHide() {
        void flushAllBodySaves(true)
      }

      const stopBeforeQuit = onBeforeQuit(() => flushAllBodySaves())

      onMounted(() => {
        document.addEventListener('visibilitychange', onBodyVisibilityChange)
        window.addEventListener('pagehide', onBodyPageHide)
        window.addEventListener('resize', measureBodyLength)
      })
      onBeforeUnmount(() => {
        document.removeEventListener('visibilitychange', onBodyVisibilityChange)
        window.removeEventListener('pagehide', onBodyPageHide)
        window.removeEventListener('resize', measureBodyLength)
        stopBeforeQuit()
        void flushAllBodySaves()
      })

      // Follow the loaded record without replacing an active draft; goal switches close stale edits.
      watch(
        () => goal.value?.id,
        (id, previousId) => {
          if (previousId && id !== previousId) void flushBodySave(previousId)
          editingBody.value = false
          moreLines.value = 0
          bodyExpanded.value = false
          openList.value = null
          fitted = false
          bodySessionId = null
          // The facts line's open-comment count needs this goal's comments whether or not the panel was ever opened.
          if (id) void store.loadCommentsFor('goal', id)
          else store.closeCommentsPanel()
        },
      )
      watch(
        () => goal.value?.body,
        () => {
          if (!editingBody.value) {
            bodyDraft.value = goal.value?.body ?? ''
            paintBody(bodyDraft.value)
          }
        },
        { immediate: true },
      )

      function onBodyClick(event: MouseEvent) {
        // A highlighted quote opens its thread instead of starting an edit.
        if (anchoring.onBodyClick(event)) return
        const link = (event.target as HTMLElement).closest('a')
        // Read-mode anchor clicks stay links and never enter edit mode.
        if (link && !editingBody.value) {
          const internal = internalLinkOf(link)
          if (internal) {
            event.preventDefault()
            void store.followBodyLink(internal)
          }
          return
        }
        if (link) event.preventDefault()
        // A click that just produced a comment selection (mouseup ran first) is a drag to select, not a caret click.
        if (!editingBody.value && !anchoring.pendingSelection.value) startBodyEdit()
      }

      function startBodyEdit() {
        if (!goal.value) return
        bodyDraft.value = goal.value.body
        bodySessionStart = goal.value.body
        bodySessionId = goal.value.id
        bodySessionPersisted = goal.value.body
        bodyExpanded.value = true
        editingBody.value = true
        anchoring.clearForEdit()
        void nextTick(() => {
          if (!bodyInputEl.value) return
          resetBodyHistory(bodyInputEl.value)
          bodyInputEl.value.focus({ preventScroll: true })
        })
      }

      function queueBodySave(id: string, body: string) {
        const pending = bodySaveTimers.get(id)
        if (pending) window.clearTimeout(pending.timer)
        const timer = window.setTimeout(() => flushBodySave(id), BODY_SAVE_DEBOUNCE_MS)
        bodySaveTimers.set(id, { timer, body })
      }

      function onBodyInput(event: InputEvent) {
        if (!goal.value || !bodyInputEl.value || !editingBody.value) return
        normalizeBodyInput(event)
        const body = serializeBodyElement(bodyInputEl.value)
        bodyDraft.value = body
        goal.value.body = body
        queueBodySave(goal.value.id, body)
      }

      function finishBodyEdit() {
        if (!editingBody.value) return
        // Navigation fires blur before pagehide: a keepalive flush, so pagehide finds no timer whose request it aborts.
        if (bodySessionId) flushBodySave(bodySessionId, true)
        if (bodyInputEl.value) renderBody(bodyInputEl.value, bodyDraft.value)
        editingBody.value = false
        bodySessionId = null
        measureBodyLength()
        anchoring.paintHighlights()
      }

      function cancelBodyEdit() {
        const cancelledId = bodySessionId
        if (bodySessionId) {
          const pending = bodySaveTimers.get(bodySessionId)
          if (pending) window.clearTimeout(pending.timer)
          bodySaveTimers.delete(bodySessionId)
        }
        if (goal.value?.id === bodySessionId) {
          goal.value.body = bodySessionStart
        }
        bodyDraft.value = bodySessionStart
        if (bodyInputEl.value) renderBody(bodyInputEl.value, bodySessionStart)
        editingBody.value = false
        bodySessionId = null
        measureBodyLength()
        anchoring.paintHighlights()
        // A debounce may already have reached storage. Escape reverts the entire session there too.
        if (cancelledId && bodySessionPersisted !== bodySessionStart) {
          void store.updateGoal(cancelledId, { body: bodySessionStart }, true)
        }
      }

      function onBodySurfaceKeydown(event: KeyboardEvent) {
        if (!editingBody.value) {
          if (event.key === 'Enter') {
            event.preventDefault()
            startBodyEdit()
          }
          return
        }
        if (event.key === 'Escape') {
          event.preventDefault()
          event.stopPropagation()
          cancelBodyEdit()
          return
        }
        handleBodyKeydown(event)
      }

      // The body's own native listeners: the shared handlers read the native event's `currentTarget` and `inputType`, and
      // blur does not bubble.
      listen(bodyInputEl, 'beforeinput', handleBodyBeforeInput)
      listen(bodyInputEl, 'input', (event) => onBodyInput(event as InputEvent))
      listen(bodyInputEl, 'keydown', onBodySurfaceKeydown)
      listen(bodyInputEl, 'paste', handleBodyPaste)
      listen(bodyInputEl, 'blur', () => { if (!keyboardHelpOpen.value) finishBodyEdit() })

      /* Documents after the notes, newest first: the goal's own (linked on lines of their own), then the ones its parents
         link, nearest parent first, are rows of its links; the ones that mention the goal and aren't in its notes are a
         line of their own, two with one title showing once, the newer. */
      const openList = ref<'documents' | 'mentions' | null>(null)
      const newestFirst = (a: DocItem, b: DocItem) => (b.updated ?? '').localeCompare(a.updated ?? '')
      const documents = computed<DocItem[]>(() => {
        // a document's own title: the link's words are the sentence's
        const known = new Map(store.state.docs.list.map((d) => [d.path, d]))
        const own = linkedDocs.value.map((d) => ({
          key: d.path,
          id: known.get(d.path)?.id,
          title: known.get(d.path)?.title || d.title,
          updated: known.get(d.path)?.updated_at ?? null,
          open: () => void store.followBodyLink({ kind: 'doc', target: d.path }),
        })).sort(newestFirst)
        const mine = new Set(own.map((d) => d.key))
        const ancestors = goal.value?.ancestors ?? []
        const nearness = new Map(ancestors.map((a, i) => [a.id, ancestors.length - i])) // 1 is the parent
        const parents = (goal.value?.docs ?? [])
          .filter((d) => d.source === 'goal' && d.inherited_from && !mine.has(d.path))
          .map((d) => ({
            key: d.path,
            id: d.id,
            title: d.title || known.get(d.path)?.title || d.path,
            updated: known.get(d.path)?.updated_at ?? null,
            open: () => store.openDocFromGoal(d.id),
            from: d.inherited_from?.title,
            fromId: d.inherited_from?.id,
          }))
          .sort((a, b) => ((nearness.get(a.fromId ?? '') ?? 99) - (nearness.get(b.fromId ?? '') ?? 99)) || newestFirst(a, b))
        return [...own, ...parents]
      })
      const mentions = computed<DocItem[]>(() => {
        const g = goal.value
        if (!g) return []
        const inNotes = new Set(g.docs.filter((d) => d.source === 'goal' && !d.inherited_from).map((d) => d.id))
        const seen = new Set<string>()
        const dated = new Map(store.state.docs.list.map((d) => [d.id, d.updated_at]))
        const all: DocItem[] = []
        for (const d of g.docs) {
          if (d.source !== 'doc' || d.inherited_from || inNotes.has(d.id)) continue
          all.push({ key: d.id, title: d.title || d.path, updated: dated.get(d.id) ?? null, open: () => store.openDocFromGoal(d.id) })
        }
        return all.sort(newestFirst).filter((d) => !seen.has(d.title) && seen.add(d.title))
      })
      const links = computed(() => documents.value.map((d) => ({ key: d.id ?? d.key, path: d.key, title: d.title, updated: d.updated, open: d.open, from: d.from })))
      const docLines = computed(() => [
        { role: 'goal-mentions', list: 'mentions' as const, docs: mentions.value, label: (n: number) => `Mentioned in ${n} ${n === 1 ? 'document' : 'documents'}` },
      ].filter((line) => line.docs.length).map((line) => ({
        ...line,
        latest: line.docs.reduce<string | null>((max, d) => (d.updated && (!max || d.updated > max) ? d.updated : max), null),
      })))
      watch(() => documents.value.length + mentions.value.length, (n) => {
        if (n && !store.state.docs.list.length && !store.state.docs.listLoading) void store.loadDocs()
      }, { immediate: true })
      function shortDate(iso: string | null): string {
        if (!iso) return ''
        const d = new Date(iso)
        return `${d.getDate()} ${MONTH_NAMES[d.getMonth()].slice(0, 3)}`
      }

      /* The opened goal is seen whole (lib/columnFit.ts), with room after the column's last card when it needs it
         (lib/columnRoom.ts). An opening the family's move draws lands the column in that movement (lib/familyMotion.ts);
         any other glides here, reading the target every frame while the goal grows, in 360-600 ms by distance. Once per
         opening; any wheel, key or press takes over. */
      let fitted = false
      let tween = 0
      function stopScroll(): void {
        if (tween) cancelAnimationFrame(tween)
        tween = 0
        for (const type of ['wheel', 'pointerdown', 'keydown', 'touchstart']) window.removeEventListener(type, stopScroll, true)
      }
      function fitIntoView(): void {
        if (fitted || tween) return
        // Opened by a held drag, it stays under the hand. Opened inside a moving family, the move has landed it.
        if (store.state.drag.id !== null || familyMoving()) { fitted = true; return }
        const detail = rootEl.value
        const block = detail ? familyBlock(detail) : null
        const scroller = block ? scrollerOf(block.list) : null
        if (!block || !scroller) return
        fitted = true
        const el = scroller
        const { card, list: open } = block
        const body = el.querySelector<HTMLElement>(':scope > .pattern-vertical-board__body')
        // Where the goal ends once open: its list and notes still grow from nothing (lib/cardFamily.ts's growList).
        const bottom = (): number => {
          const clip = open.querySelector<HTMLElement>('.goal-detail-inline__clip')
          const notes = clip ? Math.max(0, clip.scrollHeight - clip.getBoundingClientRect().height) : 0
          return contentTop(open, el) + Math.max(open.offsetHeight, open.scrollHeight + notes)
        }
        const target = (from: number): number => {
          const to = fitScroll(el, contentTop(card, el), bottom(), from)
          if (body) roomFor(el, body, to)
          return to
        }
        // The glide starts from wherever the first frame finds the column: GoalCard holds the clicked card in place first.
        // Without motion the column jumps at once, and keeps up with the goal while it grows.
        const reduced = reducedMotion()
        if (reduced) el.scrollTop = target(el.scrollTop)
        let from = reduced ? el.scrollTop : Number.NaN
        let ms = OPEN_MS
        let start = performance.now()
        let last = Number.NaN
        let still = 0
        const step = () => {
          // performance.now(), not the frame's time stamp: the opening's own work delays the first frame, and a stale
          // stamp made the glide jump
          const now = performance.now()
          if (Number.isNaN(from)) {
            from = el.scrollTop
            ms = Math.min(600, Math.max(OPEN_MS, 250 + 0.3 * Math.abs(target(from) - from)))
            start = now
          }
          const t = Math.min(1, (now - start) / ms)
          const to = target(from)
          el.scrollTop = reduced ? to : from + (to - from) * (1 - (1 - t) ** 3)
          still = Math.abs(to - last) < 0.5 ? still + 1 : 0
          last = to
          tween = t < 1 || (still < 3 && now - start < ms + 600) ? requestAnimationFrame(step) : 0
          if (!tween) stopScroll()
        }
        tween = requestAnimationFrame(step)
        for (const type of ['wheel', 'pointerdown', 'keydown', 'touchstart']) window.addEventListener(type, stopScroll, { capture: true, passive: true })
      }

      return {
        goal, loading, rootEl, bodyInputEl, editingBody, bodyExpanded, PREVIEW_PX, folded, moreLabel, anchoring,
        onBodyClick, links, docLines, openList, shortDate,
      }
    })()

    return notes
  })

  const goal = s.goal.value
  const selection = s.anchoring.pendingSelection.value
  const notes = (
      <div className="goal-detail-inline__clip">
        <div className="goal-detail__drawer-plane">
          <div
            className="goal-detail-inline__dialog"
            role="group"
            aria-label={goal?.title ?? 'Goal'}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="goal-detail__drawer-card">
              {s.loading.value ? (
                <p className="goal-detail__loading t-caption t-muted">Loading…</p>
              ) : goal ? (
                <GoalDetailEditor
                  id={goal.id}
                  title={goal.title}
                  done={goal.done_at !== null}
                  tags={goal.tags}
                  vertical={goal.vertical}
                  periodKey={goal.period_key}
                  anchorDate={goal.anchor_date}
                  repeat={goal.repeat}
                  inline
                >
                  {/* `is-selectable`: the app's global `user-select: none` would block the read-mode drag-select that
                      captures a comment's quote. */}
                  <div
                    ref={bindRef(s.bodyInputEl)}
                    className={cx('goal-detail__body is-selectable', { 'goal-detail__body--collapsed': s.folded.value })}
                    style={sx({ '--goal-body-preview-height': `${s.PREVIEW_PX}px` })}
                    data-cap="edit-body"
                    data-placeholder="Notes"
                    tabIndex={0}
                    role="textbox"
                    aria-multiline="true"
                    aria-label="Edit body"
                    contentEditable={s.editingBody.value ? 'true' : 'false'}
                    suppressContentEditableWarning
                    spellCheck="false"
                    translate="no"
                    onClick={(event) => s.onBodyClick(event.nativeEvent)}
                    onMouseDown={() => s.anchoring.onBodyMouseDown()}
                    onMouseUp={() => s.anchoring.onBodyMouseUp()}
                  ></div>
                  {s.folded.value ? (
                    <button
                      type="button"
                      className="goal-detail__body-more"
                      data-role="body-more"
                      onClick={() => {
                        s.bodyExpanded.value = true
                      }}
                    >{s.moreLabel.value}</button>
                  ) : null}
                  {/* Selecting body text offers this, at the selection's own bounding box. */}
                  {selection ? (
                    <button
                      type="button"
                      className="goal-detail__comment-selection"
                      data-cap="comment-selection"
                      style={sx({ left: `${s.anchoring.selectionButtonPos.value.x}px`, top: `${s.anchoring.selectionButtonPos.value.y}px` })}
                      onMouseDown={(event) => {
                        event.preventDefault()
                        s.anchoring.commitSelectionToComment()
                      }}
                    >Comment</button>
                  ) : null}
                  <GoalLinks goalId={goal.id} goalTitle={goal.title} body={goal.body} docs={s.links.value}
                    inWindow={store.state.openGoalVertical === 'window'} />
                  {s.docLines.value.map((line) => (
                    <Fragment key={line.list}>
                      <button
                        type="button"
                        className="goal-detail__mentions"
                        data-role={line.role}
                        aria-expanded={String(s.openList.value === line.list) as 'true' | 'false'}
                        onClick={() => {
                          s.openList.value = s.openList.value === line.list ? null : line.list
                        }}
                      ><b>{line.label(line.docs.length)}</b>{line.latest ? <><span className="goal-detail__mentions-sep" aria-hidden="true">·</span>latest {s.shortDate(line.latest)}</> : null}</button>
                      {s.openList.value === line.list ? (
                        <ul className="goal-detail__mention-list" data-role={`${line.role}-list`}>
                          {line.docs.map((doc: DocItem, i) => (
                            <Fragment key={doc.key}>
                              {doc.fromId && doc.fromId !== line.docs[i - 1]?.fromId ? (
                                <li className="goal-detail__mention-from">From {doc.from}</li>
                              ) : null}
                              <li>
                                <button
                                  type="button"
                                  data-doc={doc.key}
                                  data-inherited={doc.fromId ? 'true' : undefined}
                                  onClick={() => doc.open()}
                                >
                                  <span>{doc.title}</span><span className="goal-detail__mention-date">{s.shortDate(doc.updated)}</span>
                                </button>
                              </li>
                            </Fragment>
                          ))}
                        </ul>
                      ) : null}
                    </Fragment>
                  ))}
                </GoalDetailEditor>
              ) : (
                <p className="goal-detail__loading t-caption t-muted">Could not load this goal.</p>
              )}
            </div>
          </div>
        </div>
      </div>
  )

  return (
    <div
      {...fallthrough({
        ref: bindRef(s.rootEl),
        id: 'goal-detail',
        className: 'goal-detail-root goal-detail-inline',
        'data-state': 'open',
        'data-role': 'inline-detail',
        'aria-hidden': 'false',
      }, attrs)}
    >{notes}</div>
  )
})
