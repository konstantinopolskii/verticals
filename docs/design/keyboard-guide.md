# Keyboard shortcut guide

The centered guide opens with `?` from a focused board goal or column or from the board's background, or through the visible Keyboard shortcuts button in any view. Escape, Close or a press outside dismisses it and restores the invoking control. Opening help preserves unfinished titles and their text selection.

The window uses the app's Commissioner font, window radius, shadow and appearance tokens. Navigate, History and Goals stay in fixed groups. Mac history keys show Command; other platforms show Ctrl. Narrow windows stack the groups and scroll the dialog; dark appearance follows the system.

On board surfaces, Left/Right changes column at the same visible row index, and Up/Down changes goal. Navigation does not wrap and skips hidden, ghost, inert and outgoing rows. Empty columns are focusable. `n` opens the existing column Add control on an unfiltered board; `f` focuses the existing field. Enter renames, Space opens details and `/` opens actions. Native buttons, checkboxes, menus and editors keep their own keys. Typing on the background still starts the field. The old global `t` listener is removed because it competed with background typing.

Nobody has to set up focus first. With nothing focused on the board, an arrow key moves the focus to the goal that had it last, or to the first goal of the leading column; on an empty board, to that column. `?` on the background opens the guide; other letters still start the field. A click on a goal focuses it, so `n`, `f`, `/`, Enter and Space work on it at once; other letters go to the field. A click on a column's empty space does not keep the focus, so typing after it still starts the field. Enter on a focused column opens its Add field, like `n`. When an Add field or a title edit closes with Enter or Escape, the focus returns to its column or goal. When the board draws a focused goal again (a new goal confirmed by the server, a period redrawn), the focus moves to the new element. The leading column follows the focus and returns to the open goal's column, or Day, when the focus leaves the columns.

Each column's Add row is a place for the keys too, after its goals: Down from the last goal reaches it, Enter or `n` opens it, and an empty column's arrows land on it. An arrow on a goal's checkbox, its actions button or a column's period bars moves on from that goal or column, so no control holds the keys. When an Add field closes, the focus returns to its Add row.

Cmd+\ or Ctrl+\ puts the circle and its field away, and only the same keys bring them back. Meanwhile letters on the board, `f` and Cmd+K do not open it; its words and the agent's answers wait in it, and the board does not filter by those words. The choice is remembered on the device.

Focus never draws a frame: a frame around a column as tall as the window drew two white lines down the board in dark mode. A focused goal takes its hover colour. A focused column lights its kind and its Add row, where `n` and Enter create; a focused Add row takes its hover colour.

The dialog explains title editing and checkbox completion. From Inbox it also notes that Enter opens a goal. With a filter, it explains that the filter must be cleared before creating a goal. Global app shortcuts do not run while the dialog is open.

Validation uses synthetic goals in the isolated UI test database. The recordings and light/dark screenshots are in `docs/screenshots/keyboard-guide/`. macOS key delivery and assistive technology require checks on their actual platforms.
