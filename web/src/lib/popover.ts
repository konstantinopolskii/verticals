export type PopoverSide = 'top' | 'right' | 'bottom' | 'left'
export type PopoverAlignment = 'start' | 'end'
export type PopoverPlacement = PopoverSide | `${PopoverSide}-${PopoverAlignment}`

export interface PopoverRect {
  x: number
  y: number
  width: number
  height: number
}

export interface PopoverSize {
  width: number
  height: number
}

export interface PopoverPlacementConfig {
  placement?: PopoverPlacement | 'auto'
  offset?: readonly [mainAxis: number, alignmentAxis: number]
  collisionPadding?: number
  sizeReserve?: number
}

export interface PopoverPosition {
  x: number
  y: number
  placement: PopoverPlacement
  side: PopoverSide
  maxWidth: number
  maxHeight: number
}

const ALL_PLACEMENTS: readonly PopoverPlacement[] = [
  'top', 'top-start', 'top-end',
  'right', 'right-start', 'right-end',
  'bottom', 'bottom-start', 'bottom-end',
  'left', 'left-start', 'left-end',
]

interface Overflow {
  top: number
  right: number
  bottom: number
  left: number
}

interface Candidate {
  placement: PopoverPlacement
  position: { x: number; y: number }
  overflow: Overflow
  alignmentOverflow: [number, number]
}

function sideOf(placement: PopoverPlacement): PopoverSide {
  return placement.split('-')[0] as PopoverSide
}

function alignmentOf(placement: PopoverPlacement): PopoverAlignment | undefined {
  return placement.split('-')[1] as PopoverAlignment | undefined
}

function oppositeSide(side: PopoverSide): PopoverSide {
  if (side === 'top') return 'bottom'
  if (side === 'bottom') return 'top'
  if (side === 'left') return 'right'
  return 'left'
}

function withSide(side: PopoverSide, alignment?: PopoverAlignment): PopoverPlacement {
  return alignment ? `${side}-${alignment}` : side
}

function inset(rect: PopoverRect, padding: number): PopoverRect {
  return {
    x: rect.x + padding,
    y: rect.y + padding,
    width: Math.max(0, rect.width - padding * 2),
    height: Math.max(0, rect.height - padding * 2),
  }
}

function coordinates(
  anchor: PopoverRect,
  surface: PopoverSize,
  placement: PopoverPlacement,
  offset: readonly [number, number],
): { x: number; y: number } {
  const side = sideOf(placement)
  const alignment = alignmentOf(placement)
  const [mainAxis, alignmentAxis] = offset
  let x = anchor.x + anchor.width / 2 - surface.width / 2
  let y = anchor.y + anchor.height / 2 - surface.height / 2

  if (side === 'top') y = anchor.y - surface.height - mainAxis
  else if (side === 'bottom') y = anchor.y + anchor.height + mainAxis
  else if (side === 'left') x = anchor.x - surface.width - mainAxis
  else x = anchor.x + anchor.width + mainAxis

  if ((side === 'top' || side === 'bottom') && alignment === 'start') {
    x = anchor.x + alignmentAxis
  } else if ((side === 'top' || side === 'bottom') && alignment === 'end') {
    x = anchor.x + anchor.width - surface.width - alignmentAxis
  } else if ((side === 'left' || side === 'right') && alignment === 'start') {
    y = anchor.y + alignmentAxis
  } else if ((side === 'left' || side === 'right') && alignment === 'end') {
    y = anchor.y + anchor.height - surface.height - alignmentAxis
  }

  return { x, y }
}

function overflowAt(position: { x: number; y: number }, surface: PopoverSize, boundary: PopoverRect): Overflow {
  return {
    top: boundary.y - position.y,
    right: position.x + surface.width - (boundary.x + boundary.width),
    bottom: position.y + surface.height - (boundary.y + boundary.height),
    left: boundary.x - position.x,
  }
}

function positive(value: number): number {
  return Math.max(0, value)
}

function candidate(
  anchor: PopoverRect,
  surface: PopoverSize,
  boundary: PopoverRect,
  placement: PopoverPlacement,
  offset: readonly [number, number],
): Candidate {
  const position = coordinates(anchor, surface, placement, offset)
  const overflow = overflowAt(position, surface, boundary)
  const side = sideOf(placement)
  const alignment = alignmentOf(placement)
  let alignmentOverflow: [number, number]
  if (side === 'top' || side === 'bottom') {
    const startSide = alignment === 'start' ? 'right' : 'left'
    const mainSide = anchor.width > surface.width
      ? (startSide === 'right' ? 'left' : 'right')
      : startSide
    alignmentOverflow = [overflow[mainSide], overflow[mainSide === 'right' ? 'left' : 'right']]
  } else {
    const startSide = alignment === 'start' ? 'bottom' : 'top'
    const mainSide = anchor.height > surface.height
      ? (startSide === 'bottom' ? 'top' : 'bottom')
      : startSide
    alignmentOverflow = [overflow[mainSide], overflow[mainSide === 'bottom' ? 'top' : 'bottom']]
  }
  return { placement, position, overflow, alignmentOverflow }
}

function mainOverflow(candidateValue: Candidate): number {
  return candidateValue.overflow[sideOf(candidateValue.placement)]
}

function chooseAuto(candidates: Candidate[]): Candidate {
  const ranked = [...candidates].sort((left, right) => {
    const leftScore = mainOverflow(left)
      + (alignmentOf(left.placement) ? left.alignmentOverflow[0] : 0)
    const rightScore = mainOverflow(right)
      + (alignmentOf(right.placement) ? right.alignmentOverflow[0] : 0)
    return leftScore - rightScore
  })
  return ranked.find(value => {
    const checkedCrossAxes = alignmentOf(value.placement) ? 1 : 2
    return mainOverflow(value) <= 0
      && value.alignmentOverflow.slice(0, checkedCrossAxes).every(overflow => overflow <= 0)
  }) ?? ranked[0]!
}

function flipPlacements(preferred: PopoverPlacement): PopoverPlacement[] {
  const side = sideOf(preferred)
  const alignment = alignmentOf(preferred)
  const opposite = oppositeSide(side)
  if (!alignment) return [preferred, opposite]
  const oppositeAlignment: PopoverAlignment = alignment === 'start' ? 'end' : 'start'
  return [
    preferred,
    withSide(side, oppositeAlignment),
    withSide(opposite, alignment),
    withSide(opposite, oppositeAlignment),
  ]
}

function chooseExplicit(candidates: Candidate[]): Candidate {
  const fitting = candidates.find(value => (
    mainOverflow(value) <= 0
    && value.alignmentOverflow[0] <= 0
    && value.alignmentOverflow[1] <= 0
  ))
  if (fitting) return fitting

  const mainAxisFit = candidates
    .filter(value => mainOverflow(value) <= 0)
    .sort((left, right) => left.alignmentOverflow[0] - right.alignmentOverflow[0])[0]
  if (mainAxisFit) return mainAxisFit

  return [...candidates].sort((left, right) => {
    const leftOverflow = Object.values(left.overflow).reduce((sum, value) => sum + positive(value), 0)
    const rightOverflow = Object.values(right.overflow).reduce((sum, value) => sum + positive(value), 0)
    return leftOverflow - rightOverflow
  })[0]!
}

function sizeLimits(
  anchor: PopoverRect,
  boundary: PopoverRect,
  placement: PopoverPlacement,
  mainAxisOffset: number,
  reserve: number,
  auto: boolean,
): PopoverSize {
  const side = sideOf(placement)
  const halfReserve = reserve / 2
  let width = Math.max(0, boundary.width - reserve)
  let height = Math.max(0, boundary.height - reserve)
  if (!auto && side === 'top') height = Math.max(0, anchor.y - mainAxisOffset - boundary.y - halfReserve)
  if (!auto && side === 'bottom') {
    height = Math.max(0, boundary.y + boundary.height - halfReserve - anchor.y - anchor.height - mainAxisOffset)
  }
  if (!auto && side === 'left') width = Math.max(0, anchor.x - mainAxisOffset - boundary.x - halfReserve)
  if (!auto && side === 'right') {
    width = Math.max(0, boundary.x + boundary.width - halfReserve - anchor.x - anchor.width - mainAxisOffset)
  }
  return { width, height }
}

/**
 * Pure popover placement. All rectangles use viewport coordinates. The collision rectangle may
 * already be the intersection of viewport and clipping ancestors; no DOM state is read here.
 */
export function placePopover(
  anchor: PopoverRect,
  surface: PopoverSize,
  viewport: PopoverRect,
  config: PopoverPlacementConfig = {},
): PopoverPosition {
  const padding = config.collisionPadding ?? 8
  const reserve = config.sizeReserve ?? 16
  const offset = config.offset ?? [4, 0]
  const boundary = inset(viewport, padding)
  const automatic = !config.placement || config.placement === 'auto'
  const placements = automatic ? ALL_PLACEMENTS : flipPlacements(config.placement as PopoverPlacement)
  const candidates = placements.map(placement => candidate(anchor, surface, boundary, placement, offset))
  const selected = automatic ? chooseAuto(candidates) : chooseExplicit(candidates)
  const limits = sizeLimits(anchor, viewport, selected.placement, offset[0], reserve, automatic)
  const effectiveSurface = {
    width: Math.min(surface.width, limits.width),
    height: Math.min(surface.height, limits.height),
  }
  const finalPosition = coordinates(anchor, effectiveSurface, selected.placement, offset)
  const side = sideOf(selected.placement)

  // Shift only along the alignment axis, matching `shift({mainAxis:true,crossAxis:false})`.
  if (side === 'top' || side === 'bottom') {
    finalPosition.x = Math.min(Math.max(finalPosition.x, boundary.x), boundary.x + boundary.width - effectiveSurface.width)
  } else {
    finalPosition.y = Math.min(Math.max(finalPosition.y, boundary.y), boundary.y + boundary.height - effectiveSurface.height)
  }

  return {
    x: finalPosition.x,
    y: finalPosition.y,
    placement: selected.placement,
    side,
    maxWidth: limits.width,
    maxHeight: limits.height,
  }
}
