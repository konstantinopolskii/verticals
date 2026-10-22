// Real AppKit menus and WKWebView, without launching the backend or touching a board.
import Cocoa
import WebKit

@main enum DesktopZoomCheck {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        let delegate = AppDelegate()
        delegate.window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1000, height: 700),
                                   styleMask: [.titled, .resizable], backing: .buffered, defer: false)
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.add(delegate, name: "zoom")
        delegate.webView = WebView(frame: delegate.window.contentView!.bounds, configuration: configuration)
        delegate.window.contentView = delegate.webView
        delegate.buildMenu()
        let defaults = UserDefaults.standard
        defer { defaults.removeObject(forKey: "PageZoom") }

        func spin(until ready: () -> Bool) {
            let deadline = Date().addingTimeInterval(5)
            while !ready() && Date() < deadline {
                RunLoop.current.run(until: Date().addingTimeInterval(0.01))
            }
        }
        func js(_ script: String) -> Any? {
            var finished = false
            var result: Any?
            delegate.webView.evaluateJavaScript(script) { value, _ in result = value; finished = true }
            spin { finished }
            return result
        }
        func press(_ key: String, _ flags: NSEvent.ModifierFlags = .command) -> Bool {
            let event = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: flags,
                                        timestamp: 0, windowNumber: delegate.window.windowNumber, context: nil,
                                        characters: key, charactersIgnoringModifiers: key,
                                        isARepeat: false, keyCode: key == "-" ? 27 : key == "0" ? 29 : 24)!
            return app.mainMenu!.performKeyEquivalent(with: event)
        }
        func start(_ value: Double) { delegate.webView.pageZoom = value; defaults.removeObject(forKey: "PageZoom") }
        func zoom() -> Double { delegate.webView.pageZoom }

        let view = app.mainMenu!.items.first { $0.title == "View" }!.submenu!
        var result: [String: Any] = ["commands": view.items.filter { !$0.isHidden }.map(\.title)]
        start(1)
        result["equalsHandled"] = press("=")
        var sizes = [zoom()]
        result["plusHandled"] = press("+", [.command, .shift]); sizes.append(zoom())
        result["minusHandled"] = press("-"); sizes.append(zoom())
        result["steps"] = sizes
        result["savedAfterStep"] = defaults.double(forKey: "PageZoom")

        start(1.5)
        result["resetHandled"] = press("0")
        result["reset"] = zoom()
        result["savedAfterReset"] = defaults.double(forKey: "PageZoom")

        start(1)
        for _ in 0..<30 { _ = press("=") }
        result["maximum"] = zoom()
        for _ in 0..<30 { _ = press("-") }
        result["minimum"] = zoom()
        result["plainEqualsHandled"] = press("=", [])
        result["afterPlainEquals"] = zoom()

        // Exercise the existing developer-panel bridge too: both controls must share one scale.
        delegate.webView.loadHTMLString("<html><body><input id='draft' value='Keep my draft'></body></html>", baseURL: nil)
        spin { !delegate.webView.isLoading }
        _ = js("document.getElementById('draft').focus(); window.webkit.messageHandlers.zoom.postMessage(1.25)")
        spin { abs(zoom() - 1.25) < 0.0001 }
        result["bridge"] = zoom()
        result["focusedBefore"] = js("document.activeElement.id") as? String ?? ""
        _ = press("=")
        result["whileEditing"] = zoom()
        result["focusedAfter"] = js("document.activeElement.id") as? String ?? ""
        result["draft"] = js("document.getElementById('draft').value") as? String ?? ""
        result["pageKnowsZoom"] = js("window.verticalsPageZoom") as? Double ?? 0

        // View → Appearance: the page's prefers-color-scheme follows the choice, and the checkmark shows it.
        defer { defaults.removeObject(forKey: "Appearance") }
        let choices = view.items.first { $0.title == "Appearance" }!.submenu!
        result["appearances"] = choices.items.map(\.title)
        func choose(_ title: String) -> [String: Any] {
            let choice = choices.items.first { $0.title == title }!
            choices.performActionForItem(at: choices.index(of: choice))
            let dark = "matchMedia('(prefers-color-scheme: dark)').matches"
            let wanted = title == "System" ? js(dark) as? Bool : title == "Dark"
            spin { js(dark) as? Bool == wanted }
            choices.items.forEach { _ = delegate.validateMenuItem($0) }
            return ["dark": js(dark) as? Bool ?? false, "saved": defaults.string(forKey: "Appearance") ?? "",
                    "checked": choices.items.filter { $0.state == .on }.map(\.title),
                    "draft": js("document.getElementById('draft').value") as? String ?? ""]
        }
        result["dark"] = choose("Dark")
        result["light"] = choose("Light")
        result["system"] = choose("System")
        result["systemFollowsMacOS"] = NSApp.appearance == nil

        // Zoom never owns the typing, clipboard, undo, or Reduce Motion shortcuts.
        result["commandCHandledByZoom"] = press("c")
        let data = try! JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
        print(String(data: data, encoding: .utf8)!)
    }
}
