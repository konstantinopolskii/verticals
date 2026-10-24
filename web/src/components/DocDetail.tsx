/* A live document's editor: title, path (rename), the body (GoalDetail's markdown
   WYSIWYG, lib/bodyMarkdown.ts and lib/bodyTextarea.ts), linked-goal chips and the History/Delete/Close row. The parent
   mounts it fresh per document (keyed by its id), so the debounced body save lands with the id and revision this
   instance opened, never on whatever document is current by then. `inWindow`: drawn in a document's window, whose head
   stands for the path and actions row; links there open beside it. */
import { keyboardHelpOpen } from '../lib/keyboard'
import type { KeyboardEvent as ReactKeyboardEvent } from 'react'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from '../reactivity'
import { KChip } from '../kit'
import { AppIcon } from './AppIcon'
import { DocCommentCard } from './DocCommentCard'
import { DocDeleteButton } from './DocDeleteButton'
import { store } from '../store'
import { openWindow } from '../lib/windows'
import type { DocDetail as DocDetailWire } from '../lib/api'
import { internalLinkOf, renderBodyElement, serializeBodyElement, type InternalLink } from '../lib/bodyMarkdown'
import { useCommentAnchoring } from '../lib/commentAnchoring'
import { clearRewritten, lightRewritten, rewritten } from '../lib/docChanges'
import { onBeforeQuit } from '../lib/beforeQuit'
import {
  handleBodyBeforeInput,
  handleBodyKeydown,
  handleBodyPaste,
  normalizeBodyInput,
  resetBodyHistory,
} from '../lib/bodyTextarea'
import { bindRef, fallthrough, sx, valueOf } from '../bind'
import { tracked } from '../tracked'
import { Teleport } from '../Teleport'
import { listen, useSetup, withDefaults } from '../setup'
import './docDetail.css'

interface Props {
  doc: DocDetailWire
  inWindow?: boolean
}
const DEFAULTS = { inWindow: false }

export const DocDetail = tracked(function DocDetail(raw: Props & Record<string, unknown>) {
  const { doc, inWindow, ...attrs } = withDefaults(raw, DEFAULTS)
  const s = useSetup({ doc, inWindow }, (props) => {
    const revision = ref(props.doc.revision)
    const rootEl = ref<HTMLElement | null>(null)

    // --- body: click-to-edit contenteditable, debounced save (as GoalDetail's body) ---

    const BODY_SAVE_DEBOUNCE_MS = 1000
    const bodyEl = ref<HTMLElement | null>(null)
    const editingBody = ref(false)
    let bodySaveTimer: number | null = null
    let bodySaveDraft: string | null = null
    /** The save on its way to the API, if any: "Check again" waits for it (lib/checkAgain.ts, `flushPending`). */
    let bodySaving: Promise<void> | null = null

    // A document's comments stand on their words and open over them (`inline`): DocCommentCard.
    const anchoring = useCommentAnchoring({
      bodyEl,
      editing: editingBody,
      targetType: 'doc',
      targetId: () => props.doc.id,
      inline: true,
    })

    /** A comment is open on its words, or being written on them. */
    const cardOpen = computed(() => {
      const c = store.state.comments
      return c.targetType === 'doc' && c.targetId === props.doc.id && (c.cardId !== null || c.pendingAnchor !== null)
    })

    function paintBody(): void {
      void nextTick(() => {
        if (bodyEl.value && !editingBody.value) {
          renderBodyElement(bodyEl.value, props.doc.body)
          anchoring.paintHighlights()
          // What an agent rewrote is lit until you write in the document (lib/checkAgain.ts, lib/docChanges.ts).
          const lit = rewritten[props.doc.id]
          if (lit) lightRewritten(bodyEl.value, lit.before)
        }
      })
    }
    paintBody()
    // A new look at the document by the agent starts clean: its earlier light goes out as the next one is made.
    watch(() => rewritten[props.doc.id], (now, was) => { if (!now && was && bodyEl.value) clearRewritten(bodyEl.value) })

    async function flushBodySave(): Promise<void> {
      if (bodySaveTimer !== null) {
        window.clearTimeout(bodySaveTimer)
        bodySaveTimer = null
      }
      if (bodySaveDraft === null) {
        await bodySaving
        return
      }
      const body = bodySaveDraft
      bodySaveDraft = null
      const saving = (async () => {
        const fresh = await store.saveDoc(props.doc.id, revision.value, { body })
        if (fresh) revision.value = fresh.revision
      })()
      bodySaving = saving
      await saving
      if (bodySaving === saving) bodySaving = null
    }

    function queueBodySave(body: string): void {
      bodySaveDraft = body
      if (bodySaveTimer !== null) window.clearTimeout(bodySaveTimer)
      bodySaveTimer = window.setTimeout(() => void flushBodySave(), BODY_SAVE_DEBOUNCE_MS)
    }

    function startBodyEdit(): void {
      editingBody.value = true
      anchoring.clearForEdit()
      // Writing puts the light out, and a comment open on words that are about to be written over closes.
      if (bodyEl.value) clearRewritten(bodyEl.value)
      delete rewritten[props.doc.id]
      store.closeCard()
      void nextTick(() => {
        if (!bodyEl.value) return
        resetBodyHistory(bodyEl.value)
        bodyEl.value.focus({ preventScroll: true })
      })
    }

    function onBodyClick(event: MouseEvent): void {
      if (anchoring.onBodyClick(event)) return
      const link = (event.target as HTMLElement).closest('a')
      if (link && !editingBody.value) {
        const internal = internalLinkOf(link)
        if (internal) {
          event.preventDefault()
          if (props.inWindow) void openBeside(internal, link)
          else void store.followBodyLink(internal)
        }
        return
      }
      if (link) event.preventDefault()
      // A click that just produced a comment selection is a drag to select, not a click that places the caret.
      if (!editingBody.value && !anchoring.pendingSelection.value) startBodyEdit()
    }

    function onBodyInput(event: InputEvent): void {
      if (!bodyEl.value || !editingBody.value) return
      normalizeBodyInput(event)
      queueBodySave(serializeBodyElement(bodyEl.value))
    }

    function finishBodyEdit(): void {
      if (!editingBody.value) return
      void flushBodySave()
      editingBody.value = false
      // Keep freshly edited words in place while their comment opens and the save is still in flight.
      if (anchoring.pendingSelection.value) anchoring.paintHighlights()
      else paintBody()
    }

    function commentOnSelection(): void {
      finishBodyEdit()
      anchoring.commitSelectionToComment()
    }

    onBeforeUnmount(onBeforeQuit(flushBodySave))
    onBeforeUnmount(() => void flushBodySave())

    // One instance is one document's whole lifetime: load on mount, close on unmount.
    onMounted(() => void store.loadCommentsFor('doc', props.doc.id))
    onBeforeUnmount(() => {
      store.closeCommentsPanel()
      delete rewritten[props.doc.id]
    })

    // An agent's rewrite (Check again, lib/checkAgain.ts) arrives as a newer copy of the document: the next save builds
    // on it, unless words of yours are still waiting out their debounce.
    watch(() => props.doc.revision, (next) => { if (bodySaveDraft === null && next > revision.value) revision.value = next })

    // The body's own native listeners: the shared handlers read the native event's `currentTarget` and `inputType`.
    const onBeforeInput = (event: Event) => handleBodyBeforeInput(event as InputEvent)
    const onInput = (event: Event) => onBodyInput(event as InputEvent)
    let listening: HTMLElement | null = null
    onMounted(() => {
      listening = bodyEl.value
      listening?.addEventListener('beforeinput', onBeforeInput)
      listening?.addEventListener('input', onInput)
      listening?.addEventListener('keydown', handleBodyKeydown)
      listening?.addEventListener('paste', handleBodyPaste)
    })
    onBeforeUnmount(() => {
      listening?.removeEventListener('beforeinput', onBeforeInput)
      listening?.removeEventListener('input', onInput)
      listening?.removeEventListener('keydown', handleBodyKeydown)
      listening?.removeEventListener('paste', handleBodyPaste)
    })

    // --- title: click-to-edit in place, commit on blur/Enter, cancel on Escape ---

    const editingTitle = ref(false)
    const titleDraft = ref(props.doc.title ?? '')
    const titleInputEl = ref<HTMLInputElement | null>(null)

    function startTitleEdit(): void {
      titleDraft.value = props.doc.title ?? ''
      editingTitle.value = true
      void nextTick(() => titleInputEl.value?.select())
    }

    async function commitTitle(): Promise<void> {
      // Enter unmounts the input, and Chromium then fires blur: without this, a second PATCH on a stale revision.
      if (!editingTitle.value) return
      editingTitle.value = false
      const next = titleDraft.value.trim()
      const current = props.doc.title ?? ''
      if (next === current) return
      const fresh = await store.saveDoc(props.doc.id, revision.value, { title: next || null })
      if (fresh) revision.value = fresh.revision
    }

    function cancelTitleEdit(): void {
      editingTitle.value = false
      titleDraft.value = props.doc.title ?? ''
    }

    // --- path: the same click-to-edit; renaming moves the doc in the tree ---

    const editingPath = ref(false)
    const pathDraft = ref(props.doc.path)
    const pathInputEl = ref<HTMLInputElement | null>(null)

    function startPathEdit(): void {
      pathDraft.value = props.doc.path
      editingPath.value = true
    }

    async function commitPath(): Promise<void> {
      if (!editingPath.value) return
      editingPath.value = false
      const next = pathDraft.value.trim()
      if (!next || next === props.doc.path) return
      const fresh = await store.saveDoc(props.doc.id, revision.value, { path: next })
      if (fresh) revision.value = fresh.revision
    }

    listen(pathInputEl, 'blur', () => { if (!keyboardHelpOpen.value) void commitPath() })
    listen(titleInputEl, 'blur', () => { if (!keyboardHelpOpen.value) void commitTitle() })

    function cancelPathEdit(): void {
      editingPath.value = false
      pathDraft.value = props.doc.path
    }

    function onLinkedGoalClick(goalId: string, event?: { currentTarget: EventTarget | null }): void {
      if (props.inWindow) {
        const title = props.doc.linked_goals.find((g) => g.goal_id === goalId)?.title ?? 'Goal'
        openWindow({ kind: 'goal', target: goalId, title }, (event?.currentTarget as Element | null) ?? null)
      } else {
        void store.navigateToGoal(goalId)
      }
    }

    /* In a window a link opens its goal or document as one more window beside it, as GoalLinks does, and the board stays
       where it is. */
    async function openBeside(link: InternalLink, from: HTMLAnchorElement): Promise<void> {
      const title = from.textContent?.trim()
      if (link.kind === 'goal') {
        openWindow({ kind: 'goal', target: link.target, title: title || 'Goal' }, from)
        return
      }
      const id = await store.docIdByPath(link.target)
      if (id) openWindow({ kind: 'doc', target: id, title: title || link.target }, from)
    }

    watch(() => [props.doc.body, props.doc.title], () => { if (!editingBody.value) paintBody() })

    return {
      rootEl, bodyEl, editingBody, anchoring, cardOpen, onBodyClick, finishBodyEdit, commentOnSelection,
      editingTitle, titleDraft, titleInputEl, startTitleEdit, commitTitle, cancelTitleEdit,
      editingPath, pathDraft, pathInputEl, startPathEdit, commitPath, cancelPathEdit, onLinkedGoalClick,
    }
  })

  function onPathKey(event: ReactKeyboardEvent): void {
    if (event.key === 'Enter') {
      event.preventDefault()
      s.startPathEdit()
    }
  }
  function onPathInputKey(event: ReactKeyboardEvent): void {
    if (event.key === 'Enter') {
      event.preventDefault()
      void s.commitPath()
    }
    if (event.key === 'Escape') {
      event.stopPropagation()
      event.preventDefault()
      s.cancelPathEdit()
    }
  }
  function onTitleKey(event: ReactKeyboardEvent): void {
    if (event.key === 'Enter') {
      event.preventDefault()
      s.startTitleEdit()
    }
  }
  function onTitleInputKey(event: ReactKeyboardEvent): void {
    if (event.key === 'Enter') {
      event.preventDefault()
      void s.commitTitle()
    }
    if (event.key === 'Escape') {
      event.stopPropagation()
      event.preventDefault()
      s.cancelTitleEdit()
    }
  }

  const pendingSelection = s.anchoring.pendingSelection.value
  const selectionAt = s.anchoring.selectionButtonPos.value
  return (
    <div {...fallthrough({ ref: bindRef(s.rootEl), className: 'doc-detail', 'data-role': 'doc-detail' }, attrs)}>
      {!inWindow ? (
        <div className="doc-detail__header">
          {!s.editingPath.value ? (
            <div
              className="doc-detail__path t-caption t-muted"
              data-role="doc-path"
              tabIndex={0}
              onClick={s.startPathEdit}
              onKeyDown={onPathKey}
            >{doc.path}</div>
          ) : (
            <input
              className="doc-detail__path-input"
              data-role="doc-path-input"
              {...valueOf(s.pathDraft.value, (event) => { s.pathDraft.value = event.currentTarget.value }, s.pathInputEl)}
              onKeyDown={onPathInputKey}
            />
          )}
          <div className="doc-detail__actions">
            <button type="button" className="doc-detail__action" data-role="doc-history-trigger" onClick={() => void store.loadHistory()}>
              <AppIcon name="history" size={16} />{' History '}
            </button>
            <DocDeleteButton id={doc.id} />
            <button type="button" className="doc-detail__action" data-role="doc-close" onClick={() => store.closeDoc()}>
              <AppIcon name="x" size={16} />
            </button>
          </div>
        </div>
      ) : null}

      {!s.editingTitle.value ? (
        <div
          className="doc-detail__title t-hero"
          data-role="doc-title"
          tabIndex={0}
          onClick={s.startTitleEdit}
          onKeyDown={onTitleKey}
        >{doc.title || '(untitled)'}</div>
      ) : (
        <input
          className="doc-detail__title doc-detail__title-input t-hero"
          data-role="doc-title-input"
          {...valueOf(s.titleDraft.value, (event) => { s.titleDraft.value = event.currentTarget.value }, s.titleInputEl)}
          onKeyDown={onTitleInputKey}
        />
      )}

      {/* is-selectable: the app's global user-select:none, opted out of for selection-to-comment. */}
      <div
        ref={bindRef(s.bodyEl)}
        className="goal-detail__body doc-detail__body is-selectable"
        data-role="doc-body"
        data-placeholder="Write…"
        data-hide-title={doc.title ?? undefined}
        tabIndex={0}
        role="textbox"
        aria-multiline="true"
        aria-label="Edit body"
        contentEditable={s.editingBody.value ? 'true' : 'false'}
        suppressContentEditableWarning
        spellCheck="false"
        translate="no"
        onClick={(event) => s.onBodyClick(event.nativeEvent)}
        onBlur={(event) => {
          if (event.target !== event.currentTarget) return
          if (!keyboardHelpOpen.value) s.finishBodyEdit()
        }}
        onMouseDown={() => s.anchoring.onBodyMouseDown()}
        onMouseUp={() => s.anchoring.onBodyMouseUp()}
      ></div>
      {/* A comment on its words, or the field to write one in, stands under them. */}
      {s.cardOpen.value && s.rootEl.value && s.bodyEl.value ? (
        <DocCommentCard host={s.rootEl.value} body={s.bodyEl.value} paints={s.anchoring.paints.value} />
      ) : null}
      {pendingSelection ? (
        <Teleport to="body">
          <button
            type="button"
            className="goal-detail__comment-selection doc-detail__comment-selection"
            data-cap="comment-selection"
            style={sx({ left: `${selectionAt.x}px`, top: `${selectionAt.y}px` })}
            onMouseDown={(event) => event.preventDefault()}
            onClick={s.commentOnSelection}
          >Comment</button>
        </Teleport>
      ) : null}

      {doc.linked_goals.length ? (
        <div className="chip-wrap doc-detail__links" data-role="doc-linked-goals">
          {doc.linked_goals.map((goal) => (
            <KChip
              key={goal.goal_id}
              data-role="doc-linked-goal-chip"
              data-goal-id={goal.goal_id}
              onClick={(event) => s.onLinkedGoalClick(goal.goal_id, event)}
            >{goal.title}</KChip>
          ))}
        </div>
      ) : null}
    </div>
  )
})
