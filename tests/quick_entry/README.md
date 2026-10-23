# Quick Entry checks

`python3 -m unittest discover -s tests/quick_entry -v`

The Python checks use a temporary state folder. A recording Chat boundary checks dispatch and HTTP idempotency; it does not stand in for live API/agent acceptance.

`swiftc -o /tmp/quick-entry-keys desktop/macos/QuickEntryKeys.swift tests/quick_entry/keys.swift && /tmp/quick-entry-keys`

Before implementation the gesture check failed at “Fn alone must open after release”; after implementation it checks isolated Fn, other keys and modifiers, release order, and duplicate events.

On macOS, start the isolated desktop gateway on 8388, then compile `QuickEntry.swift`, `QuickEntryKeys.swift`, and `native_smoke.swift` together. This opens a real AppKit panel, sends Return and Cmd+Return through its WKWebView, checks Escape, opens a task with a real Codex session, and forces a network error. It writes PNGs to `/tmp/quick-entry-evidence`. It creates synthetic Inbox tasks in that gateway. It does not test a physical Fn press or Spaces; those need native permissions and owner acceptance.

Run `python tests/quick_entry/bubble_check.py` against the isolated gateway to check both keyboard actions, Shift+Enter, long input, retained text after failure, and the absence of buttons in WebKit. It records the native bridge; native_smoke covers the real bridge and API.

For the native partial-failure focus check, run `python tests/quick_entry/partial_gateway.py <existing-test-goal-id>`, then `/tmp/quick-bubble-smoke --partial`. The fixture returns a saved goal and a launch failure; it does not emulate successful agent execution. Stop the fixture afterwards.

Compile `native_access.swift` with QuickEntry and QuickEntryKeys to verify single default Carbon registration, hotkey dispatch and rebinding. Run it while the test app is closed to avoid competing for its shortcut. The default must not install modifier-only event monitors.

Run feedback_check.py against the isolated app to verify stable height during send, text-only feedback without a line, success labels, error text retention and reduced motion. Native smoke additionally checks the visible acknowledgement and that a delayed close cannot dismiss a new capture opened during confirmation.
