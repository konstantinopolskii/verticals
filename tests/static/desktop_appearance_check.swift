import Cocoa
import WebKit

@main enum AppearanceCheck {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        app.appearance = NSAppearance(named: .aqua)
        let content = NSView()
        var window: NSWindow!
        // WINDOW_CONFIGURATION
        let web = WKWebView(frame: window.contentView!.bounds)
        window.contentView = web
        window.orderFront(nil)

        func spin(until ready: () -> Bool) {
            let end = Date().addingTimeInterval(4)
            while !ready() && Date() < end {
                RunLoop.current.run(until: Date().addingTimeInterval(0.01))
            }
        }
        func js(_ script: String) -> Any? {
            var done = false
            var value: Any?
            web.evaluateJavaScript(script) { result, _ in value = result; done = true }
            spin { done }
            return value
        }
        web.loadHTMLString("<html><input id='draft' value='Keep my draft'></html>", baseURL: nil)
        spin { !web.isLoading }
        var states: [[String: Any]] = []
        for name in [NSAppearance.Name.aqua, .darkAqua, .aqua] {
            app.appearance = NSAppearance(named: name)
            let dark = name == .darkAqua
            spin { (js("matchMedia('(prefers-color-scheme: dark)').matches") as? Bool) == dark }
            var background: CGFloat = 0
            window.effectiveAppearance.performAsCurrentDrawingAppearance {
                background = window.backgroundColor.usingColorSpace(.deviceRGB)!.redComponent
            }
            states.append([
                "nativeDark": window.effectiveAppearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua,
                "webDark": js("matchMedia('(prefers-color-scheme: dark)').matches") as? Bool ?? false,
                "background": background,
                "draft": js("document.getElementById('draft').value") as? String ?? "",
            ])
        }
        print(String(data: try! JSONSerialization.data(withJSONObject: states), encoding: .utf8)!)
    }
}
