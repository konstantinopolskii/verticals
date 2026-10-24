# Keyboard shortcut guide

The centered guide opens with `?` from a focused board goal or column, or through the visible Keyboard shortcuts button in any view. Escape, Close or a press outside dismisses it and restores the invoking control. Opening help preserves unfinished titles and their text selection.

The window uses the app's Commissioner font, window radius, shadow and appearance tokens. Navigate, History and Goals stay in fixed groups. Mac history keys show Command; other platforms show Ctrl. Narrow windows stack the groups and scroll the dialog; dark appearance follows the system.

On board surfaces, Left/Right changes column at the same visible row index, and Up/Down changes goal. Navigation does not wrap and skips hidden, ghost, inert and outgoing rows. Empty columns are focusable. `n` opens the existing column Add control on an unfiltered board; `f` focuses the existing field. Enter renames, Space opens details and `/` opens actions. Native buttons, checkboxes, menus and editors keep their own keys. Typing on the background still starts the field. The old global `t` listener is removed because it competed with background typing.

The dialog explains title editing and checkbox completion. From Inbox it also notes that Enter opens a goal. With a filter, it explains that the filter must be cleared before creating a goal. Global app shortcuts do not run while the dialog is open.

Validation uses synthetic goals in the isolated UI test database. The recordings and light/dark screenshots are in `docs/screenshots/keyboard-guide/`. macOS key delivery and assistive technology require checks on their actual platforms.
