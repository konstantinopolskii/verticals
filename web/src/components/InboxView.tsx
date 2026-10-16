/* The Inbox: everything with no date and every document, on the desk's grey. Today's
   tasks on top, big, the last three and the rest behind "N more"; under them Earlier, Documents and Sources, each a row
   you swipe that "Show all" opens onto shelves. While you write in the field the desk goes quiet behind it. A carried
   task is drawn over everything, in the body. */
import { Fragment } from 'react'
import { computed, onBeforeUnmount, onMounted, watch } from '../reactivity'
import { DeskHead } from './DeskHead'
import { DocChip } from './DocChip'
import { InboxCard } from './InboxCard'
import { InboxTile } from './InboxTile'
import { store } from '../store'
import { commandFilter } from '../lib/commandFilter'
import { inboxWriting } from '../lib/circle'
import { docShelves, earlier, inbox, inboxView, loadInbox, recentDocs, shelves, today, TODAY_SHOWN } from '../lib/inbox'
import { desk, loadDesk } from '../lib/docsDesk'
import { cardOf, loadSources, noSourcesLine, noteOf, realSources, sources } from '../lib/sources'
import { carry } from '../lib/inboxCarry'
import { Teleport } from '../Teleport'
import { cx, fallthrough, sx } from '../bind'
import { tracked } from '../tracked'
import { useSetup } from '../setup'
import './inboxView.css'

/* A row holds the newest; "Show all" holds everything. */
const ROW = 24

export const InboxView = tracked(function InboxView(attrs: Record<string, unknown>) {
  const s = useSetup({}, () => {
    const todayShown = computed(() => (inboxView.allToday ? today.value : today.value.slice(0, TODAY_SHOWN)))
    const hiddenToday = computed(() => today.value.length - TODAY_SHOWN)

    const onDocEdited = () => { void loadDesk(); void loadSources() }
    onMounted(() => {
      void loadInbox()
      void loadDesk()
      void loadSources()
      window.addEventListener('verticals:doc-edited', onDocEdited)
    })
    onBeforeUnmount(() => window.removeEventListener('verticals:doc-edited', onDocEdited))
    // Every board load follows a write somewhere: the Inbox reads again with it.
    watch(() => store.state.board, () => { void loadInbox(); void loadSources() })
    return { todayShown, hiddenToday }
  })

  return (
    <div {...fallthrough({ className: cx('inbox-desk', { 'inbox-desk--writing': inboxWriting.value && !!commandFilter.text }), 'data-cap': 'inbox' }, attrs)}>
      <DeskHead title="Inbox" />
      {today.value.length ? (
        <section className="inbox-desk__today" data-role="inbox-today">
          {s.todayShown.value.map((item) => <InboxCard key={item.id} item={item} finding={inbox.finding.includes(item.id)} />)}
          {s.hiddenToday.value > 0 ? (
            <button type="button" className="inbox-desk__more" data-role="inbox-more" onClick={() => { inboxView.allToday = !inboxView.allToday }}>
              {inboxView.allToday ? 'Show fewer' : `${s.hiddenToday.value} more`}{' '}
              <svg width="11" height="11" viewBox="0 0 9 9" aria-hidden="true">
                <path d={inboxView.allToday ? 'M2 5.5 4.5 3 7 5.5' : 'M2 3.5 4.5 6 7 3.5'} fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          ) : null}
        </section>
      ) : null}

      {earlier.value.length ? (
        <section className="inbox-desk__section" data-role="inbox-earlier">
          <h2 className="inbox-desk__head">
            Earlier<span className="inbox-desk__count">{earlier.value.length}</span>
            <button type="button" className="inbox-desk__all" data-role="inbox-earlier-all" onClick={() => { inboxView.earlier = !inboxView.earlier }}>
              {inboxView.earlier ? 'Show less' : 'Show all'}
            </button>
          </h2>
          {inboxView.earlier ? (
            shelves.value.map((shelf) => (
              <Fragment key={shelf.vertical}>
                <h3 className="inbox-desk__shelf" data-shelf={shelf.vertical}>{shelf.name}<span>{shelf.goals.length}</span></h3>
                <div className="inbox-desk__grid">{shelf.goals.map((goal) => <InboxTile key={goal.id} item={goal} />)}</div>
              </Fragment>
            ))
          ) : (
            <div className="inbox-desk__row">{earlier.value.slice(0, ROW).map((goal) => <InboxTile key={goal.id} item={goal} />)}</div>
          )}
        </section>
      ) : null}

      {recentDocs.value.length ? (
        <section className="inbox-desk__section" data-role="inbox-docs">
          <h2 className="inbox-desk__head">
            Documents<span className="inbox-desk__count">{recentDocs.value.length}</span>
            <button type="button" className="inbox-desk__all" data-role="inbox-docs-all" onClick={() => { inboxView.docs = !inboxView.docs }}>
              {inboxView.docs ? 'Show less' : 'Show all'}
            </button>
          </h2>
          {inboxView.docs ? (
            docShelves.value.map((shelf) => (
              <Fragment key={shelf.vertical}>
                <h3 className="inbox-desk__shelf" data-shelf={shelf.vertical}>{shelf.name}<span>{shelf.docs.length}</span></h3>
                <div className="inbox-desk__grid">{shelf.docs.map((doc) => <DocChip key={doc.id} id={doc.id} doc={doc} />)}</div>
              </Fragment>
            ))
          ) : (
            <div className="inbox-desk__row">{recentDocs.value.slice(0, ROW).map((doc) => <DocChip key={doc.id} id={doc.id} doc={doc} />)}</div>
          )}
        </section>
      ) : null}

      {sources.loaded ? (
        <section className="inbox-desk__section" data-role="inbox-sources">
          <h2 className="inbox-desk__head">
            Sources{realSources.value.length ? <span className="inbox-desk__count">{realSources.value.length}</span> : null}
            {sources.list.length > 4 ? (
              <button type="button" className="inbox-desk__all" data-role="inbox-sources-all" onClick={() => { inboxView.sources = !inboxView.sources }}>
                {inboxView.sources ? 'Show less' : 'Show all'}
              </button>
            ) : null}
          </h2>
          {realSources.value.length ? null : (
            <p className="inbox-desk__empty inbox-desk__none" data-role="inbox-sources-none">{noSourcesLine()}</p>
          )}
          {sources.list.length ? (
            <div className={inboxView.sources ? 'inbox-desk__grid' : 'inbox-desk__row'}>
              {(inboxView.sources ? sources.list : sources.list.slice(0, ROW)).map((source) => (
                <DocChip key={source.id} id={source.id} doc={cardOf(source)} note={noteOf(source).text} tone={noteOf(source).tone} />
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {inbox.loaded && desk.loaded && !inbox.goals.length && !recentDocs.value.length && !realSources.value.length ? (
        <p className="inbox-desk__empty">
          Nothing waits here. What you write in the field lands at the top.
        </p>
      ) : null}

      <Teleport to="body">
        {carry.item ? (
          <div className="inbox-carried" data-role="inbox-carried" style={sx({ left: `${carry.x}px`, top: `${carry.y}px`, width: `${carry.width}px` })}>
            <InboxTile item={carry.item} />
          </div>
        ) : null}
      </Teleport>
    </div>
  )
})
