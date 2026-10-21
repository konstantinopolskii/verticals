/* A window's head: a document's facts and versions, a page's title and its way out to Chrome, and ×. A goal has only
   ×, which closes every window. */
import { Fragment } from 'react'
import { AppIcon } from './AppIcon'
import { DocDeleteButton } from './DocDeleteButton'
import { closeWindow, closeWindows, type VtWindow } from '../lib/windows'
import { store } from '../store'
import { cx } from '../bind'
import { tracked } from '../tracked'

type HeadPart = { text: string; act?: 'versions' }

function headParts(win: VtWindow): HeadPart[] {
  const parts: HeadPart[] = (win.facts ?? []).map((text) => ({ text }))
  if ((win.versions ?? 0) > 1) parts.push({ text: `${win.versions} versions`, act: 'versions' })
  return parts
}

function openHistory(win: VtWindow): void {
  closeWindow(win.key)
  void store.openHistoryOf(win.target)
}

export const WindowHead = tracked(function WindowHead({ win }: { win: VtWindow }) {
  if (win.kind === 'goal') {
    return (
      <button type="button" className="vt-window__button vt-window__close" aria-label="Back to the board"
        data-role="window-close" onClick={(event) => { event.stopPropagation(); closeWindows() }}>
        <AppIcon name="x" size={16} />
      </button>
    )
  }
  return (
    <header className={cx('vt-window__head', {
      'vt-window__head--doc': win.kind === 'doc',
      'is-titled': win.kind === 'doc' && win.titled,
    })}>
      {win.kind === 'doc' ? (
        <>
          <AppIcon className="vt-window__icon" name="file" size={16} />
          <p className="vt-window__facts" data-role="doc-facts">
            {win.titled ? (
              <>
                <b className="vt-window__title" data-role="doc-head-title">{win.title}</b>
                <span className="vt-window__sep">·</span>
              </>
            ) : null}
            {headParts(win).map((part, i) => (
              <Fragment key={i}>
                {i ? <span className="vt-window__sep">·</span> : null}
                {part.act ? (
                  <button type="button" className="vt-window__act" data-role={`doc-${part.act}`}
                    onClick={(event) => { event.stopPropagation(); openHistory(win) }}>{part.text}</button>
                ) : part.text}
              </Fragment>
            ))}
          </p>
          <DocDeleteButton id={win.target} />
        </>
      ) : (
        <h2 className="vt-window__name" title={win.title}>{win.title}</h2>
      )}
      {win.kind === 'page' ? (
        <a className="vt-window__button" href={win.target} target="_blank" rel="noreferrer" aria-label="Open in Chrome"
          title="Open in Chrome"><AppIcon name="arrow-up-right" size={16} /></a>
      ) : null}
      <button type="button" className="vt-window__button" aria-label="Close"
        onClick={(event) => { event.stopPropagation(); closeWindow(win.key) }}><AppIcon name="x" size={16} /></button>
    </header>
  )
})
