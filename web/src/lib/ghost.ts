// A still copy of a piece of the screen, for a change of view that crossfades (docs/design-handoff S5.P1.023, S5.P6.009):
// it stands exactly where the original stood, takes no pointer and carries none of the original's hooks, so the drag and
// the tests never find it.
const HOOKS = ['id', 'data-goal-id', 'data-dots-vertical', 'data-span-start', 'data-span-edge', 'data-parked', 'data-role', 'data-cap']

export function ghostOf(el: HTMLElement): HTMLElement {
  const rect = el.getBoundingClientRect()
  const ghost = el.cloneNode(true) as HTMLElement
  for (const node of [ghost, ...ghost.querySelectorAll<HTMLElement>('*')]) {
    for (const name of HOOKS) node.removeAttribute(name)
  }
  Object.assign(ghost.style, {
    position: 'fixed',
    inset: 'auto',
    left: `${rect.left}px`,
    top: `${rect.top}px`,
    width: `${rect.width}px`,
    height: `${rect.height}px`,
    margin: '0',
    pointerEvents: 'none',
  })
  ghost.setAttribute('aria-hidden', 'true')
  ghost.inert = true
  return ghost
}
