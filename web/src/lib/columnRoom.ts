/* Room after a column's last card (KK, 27 Sep 2026: an opened goal "should appear at the top, not to scroll a bit at a
   bottom"). A goal near its column's end can't scroll to the top, so while it's open the column gets just enough empty
   room after its last card (`GoalDetail.vue` asks for it every frame of the opening). When the goal closes, the room
   stays as long as it's in view and shrinks as the column scrolls back up, so closing moves nothing. */

type Room = { body: HTMLElement; scroller: HTMLElement; base: number; px: number; trim: (() => void) | null }
const rooms = new WeakMap<HTMLElement, Room>()

function stopTrim(room: Room): void {
  if (room.trim) room.scroller.removeEventListener('scroll', room.trim)
  room.trim = null
}

function apply(room: Room, px: number): void {
  const next = Math.max(0, Math.ceil(px))
  if (next && next === room.px) return // the same room: writing it again lays the column out again, every frame of the glide
  room.px = next
  if (room.px) { room.body.style.paddingBottom = `${room.base + room.px}px`; return }
  room.body.style.removeProperty('padding-bottom')
  stopTrim(room)
  rooms.delete(room.body)
}

/** Enough room after `body`'s last card for `scroller` to scroll to `scrollTop`, and no more. */
export function roomFor(scroller: HTMLElement, body: HTMLElement, scrollTop: number): void {
  let room = rooms.get(body)
  if (!room) {
    room = { body, scroller, base: parseFloat(getComputedStyle(body).paddingBottom) || 0, px: 0, trim: null }
    rooms.set(body, room)
  }
  stopTrim(room)
  const reach = scroller.scrollHeight - room.px - scroller.clientHeight // how far the cards alone let it scroll
  apply(room, scrollTop - reach)
}

const FOLD_MS = 400 // the open goal folds away in 360 ms (goalCard.css, goalDetail.css)

/** The open goal is closing. The column keeps its place: the room grows by more than the goal can fold by, with no
 *  layout read (a read in the middle of the close would let the column clamp at once), and stays so while the goal folds
 *  away. Then it is only what keeps the column where it is, and it goes as the column scrolls back up, never while it's
 *  in view. */
export function leaveRoom(body: HTMLElement | null): void {
  const room = body ? rooms.get(body) : undefined
  if (!room) return
  stopTrim(room)
  apply(room, room.px + 4 * window.innerHeight)
  const trim = () => {
    const cardsEnd = room.scroller.scrollHeight - room.px
    apply(room, room.scroller.scrollTop + room.scroller.clientHeight - cardsEnd)
  }
  room.trim = trim
  setTimeout(() => {
    if (room.trim !== trim) return // a goal opened here meanwhile and took the room over
    room.scroller.addEventListener('scroll', trim, { passive: true })
    trim()
  }, FOLD_MS)
}
