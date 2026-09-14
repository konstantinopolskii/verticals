/** Commit one native checkbox change, then animate its measured 200 ms visual state. */
export function commitCheckboxChange(
  event: Event,
  commit: (value: boolean) => void,
): void {
  const input = event.target as HTMLInputElement
  const value = input.checked
  commit(value)
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
  const box = input.nextElementSibling as HTMLElement | null
  const check = box?.querySelector<SVGPathElement>('.checkbox__check')
  const timing = { duration: 200, easing: 'cubic-bezier(.165,.84,.44,1)' }
  box?.animate(
    [
      {
        backgroundColor: value ? 'transparent' : '#357cf4',
        borderColor: value ? 'rgba(40, 42, 47, .17)' : '#357cf4',
        transform: 'scale(1.1)',
      },
      {
        backgroundColor: value ? '#357cf4' : 'transparent',
        borderColor: value ? '#357cf4' : 'rgba(40, 42, 47, .17)',
        transform: 'scale(1)',
      },
    ],
    timing,
  )
  check?.animate(
    [
      { strokeDashoffset: value ? '17' : '0' },
      { strokeDashoffset: value ? '0' : '17' },
    ],
    timing,
  )
}
