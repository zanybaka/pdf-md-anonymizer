# ADR-0009: Status-bar implementation uses Toga's native MenuStatusIcon

- Status: Accepted
- Date: 2026-05-19
- Realized by: UI-004

## Context

UI-004 adds an opt-in "Stay in menu bar when window is closed" mode. When
enabled, closing the main window hides it and a macOS status-bar icon appears
with a mini-menu (Show Window, Anonymize to Clipboard, About, Quit).

The first implementation hand-rolled an `NSStatusItem` via rubicon-objc: it
created the item with `NSStatusBar.systemStatusBar`, built an `NSMenu`
programmatically, and wired each menu item to a custom `NSObject` target via
target-action selectors. That approach did not work — menu items showed but
clicking them dispatched no action (even a system `terminate:` item failed),
because the custom ObjC target/action plumbing did not integrate with the
event loop and responder chain Toga sets up on macOS.

Three options were evaluated:

| Option | Pros | Cons |
|--------|------|------|
| Hand-rolled rubicon-objc `NSStatusItem` | No new deps | Target-action dispatch does not work under Toga's Cocoa run loop; manual `NSMenu`/`NSStatusItem` lifecycle; ObjC class registration is fragile |
| **Toga `MenuStatusIcon`** | First-class Toga API (Toga 0.5+); command dispatch goes through Toga's own machinery and works reliably; async command handlers supported; standard About/Quit provided automatically | Requires Toga ≥ 0.5 |
| `rumps` | Higher-level Python API | New runtime dependency; pulls its own ObjC bridge; may conflict with Toga's rubicon usage |

The original ADR assumed "Toga has no built-in status-bar API." That premise
was wrong: Toga 0.5 ships `toga.MenuStatusIcon` / `toga.SimpleStatusIcon`.

## Decision

Use **Toga's native `toga.MenuStatusIcon`**. The status icon is registered
through `app.status_icons`, and menu entries are ordinary `toga.Command`
instances grouped under the `MenuStatusIcon`. Toga's command machinery handles
the `NSStatusItem`/`NSMenu` lifecycle and action dispatch, so no custom ObjC
target class is needed. The standard About and Quit commands are added to the
primary status icon automatically by Toga.

All menu entries ("Show Window", "Anonymize to Clipboard…", "Quit") are
explicit `toga.Command` instances grouped under the `MenuStatusIcon`; Toga's
auto-added standard About/Quit commands for status icons are dropped so the
ordering and the section separator above "Quit" are fully controlled. The
clipboard handler is a normal `async` handler.

rubicon-objc is still used for the remaining low-level bits that Toga does not
cover: hiding the window (`NSWindow.orderOut:`), toggling the Dock icon
(`NSApplication.setActivationPolicy:`), and user notifications. No new package
is added.

## Consequences

- The project requires Toga ≥ 0.5 (already satisfied).
- The status icon is added/removed via `app.status_icons.add`/`remove`; the
  `MenuStatusIcon` instance and its commands are created once and reused
  across add/remove cycles so command-to-group references stay valid.
- Notifications still use `NSUserNotificationCenter` (deprecated macOS 11+ but
  functional) to avoid the block-callback complexity of
  `UNUserNotificationCenter` with rubicon-objc.
