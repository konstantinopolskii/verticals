/* The field's size in each of its states (components/SearchBar.tsx): what it holds sets its width and height, and the
   shape follows them (circleField.css). */
import type { ChipLink } from './chipLinks'
import type { CircleState } from './circle'

export const ANSWER_MEASURE = 376
const ANSWER_PAD = 44
export const PAD_LEFT = 32
const PAD_RIGHT = 84
export const PAD_Y = 24
export const LINE = 36
export const CIRCLE = 84
/* While the agent works the circle is a pill with its step written beside the turning line (AgentStep): the line stays where
   the circle's centre was, 42 px in, and the stop square takes the right end. One width for every phrase, so the black moves
   when the work begins and ends, not with each step. */
const STEP_WIDTH = 360
/* The open field's caption has 32 px on each side. */
const PAD_CAPTION = 32
const OPEN_WIDTH = 272
/* A message bringing chips is the balloon in the field: the words 376 px wide, two lines of them, 32 px in from the sides,
   then the chips with 14 px between (the balloon's own), three at most and "N more" for the rest. */
const CHIPS_PAD = 32
export const CHIPS_SHOWN = 3
const CHIPS_GAP = 14
const CHIP_HEIGHT = { doc: 67, goal: 44 }
/* An answer that changed the board has its Undo at its end, under its words and its chips (AnswerUndo): the notice's
   pill, 40 px tall and about 80 wide, 12 px under what is above it. */
const UNDO_ROW = 52
const UNDO_W = 80
/* A line of the answer's words. */
const ANSWER_LINE = 22

export interface WidthIn {
  state: CircleState
  maxWidth: number
  /** The caption's width and the typed words' width, as set in the field. */
  caption: number
  typed: number
  carryOver: boolean
  holding: boolean
  chips: number
  answerWidth: number
  leadLines: number
  undoable: boolean
  stepShown: boolean
  stopping: boolean
  tagsShown: boolean
  game: boolean
}

export interface HeightIn {
  state: CircleState
  lines: number
  chips: number
  chipsHeight: number
  /** The answer has words of its own, above its chips. */
  words: boolean
  answerLines: number
  leadLines: number
  ask: boolean
  choices: boolean
  undoable: boolean
}

/** Open, the field is as wide as "Write to inbox" at least, and wider only for a longer caption. */
function openWidth(f: WidthIn): number {
  return Math.min(f.maxWidth, Math.max(OPEN_WIDTH, Math.ceil(PAD_CAPTION + f.caption + PAD_CAPTION)))
}

export function fieldWidth(f: WidthIn): number {
  if (f.carryOver) return 120
  if (f.state === 'answer' && f.chips) return ANSWER_MEASURE + 2 * CHIPS_PAD
  if (f.state === 'answer') {
    const wide = Math.min((f.leadLines ? ANSWER_MEASURE : f.answerWidth) + 2 * ANSWER_PAD, ANSWER_MEASURE + 2 * ANSWER_PAD)
    return Math.max(CIRCLE, wide, f.undoable ? UNDO_W + 2 * ANSWER_PAD : 0)
  }
  if (f.stepShown) return Math.min(STEP_WIDTH, f.maxWidth)
  if (f.stopping) return 132
  // Typing, it grows around your words and never gets narrower than it was open, so the first key moves nothing.
  if (f.state === 'typing') return Math.min(f.maxWidth, Math.max(openWidth(f), Math.ceil(PAD_LEFT + PAD_RIGHT + f.typed + 5)))
  if (f.state === 'open') return openWidth(f)
  if (f.holding) return 120
  // The buttons stand at the stack's left end whenever they are shown, pointed at or holding the keys, and the stack
  // stands right of them (S5.P3.010, .012): the field is wide enough for both, with the hand on it or away.
  if (f.state === 'moving') return Math.min(f.tagsShown ? 434 : 300, f.maxWidth)
  return f.game ? 132 : CIRCLE
}

export function fieldHeight(f: HeightIn): number {
  const undo = f.undoable ? UNDO_ROW : 0
  if (f.state === 'typing') return PAD_Y * 2 + f.lines * LINE
  if (f.state === 'answer' && f.chips) {
    // The words above the chips: two lines at most, and 14 px to the first chip.
    const words = f.words ? Math.min(2, f.answerLines) * ANSWER_LINE + CHIPS_GAP : 0
    return Math.max(CIRCLE, PAD_Y * 2 + words + f.chipsHeight + undo)
  }
  if (f.state === 'answer') {
    const ask = f.ask ? (f.choices ? 44 : 0) + (f.leadLines ? f.leadLines * ANSWER_LINE + 8 : 0) : 0
    return Math.max(CIRCLE, PAD_Y * 2 + f.answerLines * ANSWER_LINE + ask + undo)
  }
  return CIRCLE
}

/** The chips' height before they are drawn: each chip's own, 12 px between, and the "N more" line. */
export function chipsGuess(shown: ChipLink[], more: number): number {
  const chips = shown.reduce((sum, chip) => sum + CHIP_HEIGHT[chip.kind] + 12, -12)
  return chips + (more ? 12 + 22 : 0)
}

/** How many lines of the answer's words `el` holds, one at least and `max` at most. */
export function answerLinesOf(el: Element, max: number): number {
  return Math.min(max, Math.max(1, Math.round(el.getBoundingClientRect().height / ANSWER_LINE)))
}
