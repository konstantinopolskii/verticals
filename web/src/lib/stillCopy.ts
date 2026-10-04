// Still copies for the board's moves (lib/familyMotion.ts): what was there before a change, as it looked, faded out
// where it stood after the change has taken it from the page, on a layer of its own in its column.

/** What a copy is made from: an element as it stood, the scale of the lifted card it stood in, and its colour's shape
 *  (a row's ::before, lib/goalWash.ts). */
export interface Copied {
  el: HTMLElement
  rect: DOMRect
  lift: number
  wash?: { top: number; right: number; bottom: number; left: number; opacity: number }
}

/* A still copy of something as it looks now, for fading it out where it was after it is gone from the page. Its look is
   written onto it, since the rules that drew it depend on where it stood; a row's colour becomes a plain box. */
const LOOK = [
  'display', 'flex-direction', 'flex-wrap', 'flex-grow', 'flex-shrink', 'flex-basis', 'align-items', 'align-self',
  'justify-content', 'gap', 'row-gap', 'column-gap', 'box-sizing', 'width', 'height', 'min-width', 'min-height',
  'padding-top', 'padding-right', 'padding-bottom', 'padding-left', 'margin-top', 'margin-right', 'margin-bottom',
  'margin-left', 'border-top-width', 'border-right-width', 'border-bottom-width', 'border-left-width', 'border-top-style',
  'border-right-style', 'border-bottom-style', 'border-left-style', 'border-top-color', 'border-right-color',
  'border-bottom-color', 'border-left-color', 'border-radius', 'background-color', 'background-image', 'box-shadow',
  'color', 'font-family', 'font-size', 'font-weight', 'font-style', 'font-variant-numeric', 'line-height',
  'letter-spacing', 'text-align', 'text-decoration-line', 'text-decoration-color', 'text-decoration-thickness',
  'white-space', 'word-break', 'overflow-wrap', 'opacity', 'visibility', 'position', 'top', 'right', 'bottom', 'left',
  'vertical-align', 'fill', 'stroke', 'filter', 'overflow',
]
function copyLook(from: Element, to: Element): void {
  const look = getComputedStyle(from)
  const style = (to as HTMLElement).style
  if (!style) return
  for (const property of LOOK) style.setProperty(property, look.getPropertyValue(property))
  for (let i = 0; i < from.children.length && i < to.children.length; i++) copyLook(from.children[i], to.children[i])
}
export function stillCopy(entry: Copied): HTMLElement {
  const copy = entry.el.cloneNode(true) as HTMLElement
  copy.removeAttribute('id')
  for (const el of copy.querySelectorAll('[id]')) el.removeAttribute('id')
  copyLook(entry.el, copy)
  if (entry.wash && entry.wash.opacity > 0.01) {
    const s = getComputedStyle(entry.el, '::before')
    const shape = document.createElement('div')
    shape.style.cssText = `position:absolute;z-index:-1;top:${entry.wash.top}px;right:${entry.wash.right}px;`
      + `bottom:${entry.wash.bottom}px;left:${entry.wash.left}px;border-radius:${s.borderRadius};`
      + `background:${s.backgroundImage !== 'none' ? `${s.backgroundImage}, ` : ''}${s.backgroundColor};opacity:${entry.wash.opacity}`
    copy.style.isolation = 'isolate'
    copy.prepend(shape)
    // an open card's colour runs on down its list, which draws that share itself (lib/goalWash.ts): the copy of its row
    // carries it too, so the copies of its steps and notes fade on their colour
    const card = entry.el.parentElement
    const list = card?.classList.contains('goal-card--detail-open') ? card.nextElementSibling : null
    if (list instanceof HTMLElement && list.classList.contains('goal-card__children--open')) {
      const p = getComputedStyle(list, '::before')
      const box = list.getBoundingClientRect()
      const k = entry.lift
      const piece = document.createElement('div')
      piece.style.cssText = `position:absolute;z-index:-1;top:${(box.top - entry.rect.top) / k + (parseFloat(p.top) || 0)}px;`
        + `left:${(box.left - entry.rect.left) / k + (parseFloat(p.left) || 0)}px;`
        + `width:${box.width / k - (parseFloat(p.left) || 0) - (parseFloat(p.right) || 0)}px;`
        + `height:${box.height / k - (parseFloat(p.top) || 0) - (parseFloat(p.bottom) || 0)}px;border-radius:${p.borderRadius};`
        + `background:${p.backgroundImage !== 'none' ? `${p.backgroundImage}, ` : ''}${p.backgroundColor}`
      copy.prepend(piece)
    }
  }
  for (const el of [copy, ...copy.querySelectorAll<HTMLElement>('*')]) {
    el.style.animation = 'none' // a copy keeps its look: no opening of its own
    el.style.transition = 'none'
  }
  copy.setAttribute('aria-hidden', 'true')
  copy.style.pointerEvents = 'none'
  copy.style.transform = 'none'
  copy.style.margin = '0'
  return copy
}

/** Each moving column draws its copies on a layer of its own, clipped with the column. */
const layers = new Map<HTMLElement, HTMLElement>()
export function layer(column: HTMLElement): HTMLElement {
  let ghosts = layers.get(column)
  if (!ghosts) {
    ghosts = document.createElement('div')
    ghosts.className = 'family-ghosts'
    ghosts.setAttribute('aria-hidden', 'true')
    layers.set(column, ghosts)
  }
  if (ghosts.parentElement !== column) column.append(ghosts)
  return ghosts
}
/** The copies on every column's layer. */
export function copies(): Element[] {
  return [...layers.values()].flatMap((ghosts) => [...ghosts.children])
}
export function clearLayers(): void {
  for (const [column, ghosts] of layers) {
    ghosts.replaceChildren()
    if (!column.isConnected) layers.delete(column)
  }
}

export function place(copy: HTMLElement, rect: DOMRect, home: DOMRect, lift = 1): void {
  copy.style.position = 'absolute'
  copy.style.left = `${rect.left - home.left}px`
  copy.style.top = `${rect.top - home.top}px`
  // a copy of a lifted thing keeps its own size and is drawn as large as it was, so its words wrap as they did
  copy.style.width = `${rect.width / lift}px`
  copy.style.height = `${rect.height / lift}px`
  copy.style.transformOrigin = '0 0'
  copy.style.transform = lift === 1 ? 'none' : `scale(${lift})`
}
