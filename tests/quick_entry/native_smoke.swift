import Cocoa
import WebKit

@main struct Smoke {
    static var delegate: Probe!
    static func main() {
        let app = NSApplication.shared
        delegate = Probe(); app.delegate = delegate; app.run()
    }
}
@MainActor final class Probe: NSObject, NSApplicationDelegate {
    var entry: QuickEntry!
    var web: WKWebView!
    var window: NSWindow!
    let output = URL(fileURLWithPath: "/tmp/quick-entry-evidence")
    func applicationDidFinishLaunching(_ note: Notification) {
        Task { do { try await check(); NSApp.terminate(nil) } catch { print("FAIL: \(error)"); exit(1) } }
    }
    func js(_ view: WKWebView, _ source: String) async throws -> Any {
        try await view.evaluateJavaScript(source)
    }
    func wait(_ view: WKWebView, _ expression: String) async throws {
        for _ in 0..<200 {
            if (try? await js(view, expression)) as? Bool == true { return }
            try await Task.sleep(nanoseconds:100_000_000)
        }
        throw NSError(domain:"Timed out: "+expression,code:1)
    }
    func picture(_ view: WKWebView, _ name: String) async throws {
        let image = try await view.takeSnapshot(configuration:nil)
        let rep = NSBitmapImageRep(data:image.tiffRepresentation!)!
        try rep.representation(using:.png,properties:[:])!.write(to:output.appendingPathComponent(name+".png"))
    }
    func type(_ text: String) async throws {
        let data = try JSONSerialization.data(withJSONObject:[text])
        let json = String(data:data,encoding:.utf8)!
        _ = try await js(entry.entryWeb,"document.querySelector('textarea').value="+json+"[0];document.querySelector('textarea').dispatchEvent(new Event('input'));true")
    }
    func key(_ code: UInt16, _ flags: NSEvent.ModifierFlags = []) {
        let event=NSEvent.keyEvent(with:.keyDown,location:.zero,modifierFlags:flags,timestamp:ProcessInfo.processInfo.systemUptime,
            windowNumber:entry.panel.windowNumber,context:nil,characters:code == 53 ? "\u{1b}" : "\r",
            charactersIgnoringModifiers:code == 53 ? "\u{1b}" : "\r",isARepeat:false,keyCode:code)!
        NSApp.sendEvent(event)
    }
    func settled() async throws {
        try await Task.sleep(nanoseconds:500_000_000)
        for _ in 0..<300 {
            if !entry.busy && entry.confirmation == nil { return }
            try await Task.sleep(nanoseconds:100_000_000)
        }
        throw NSError(domain:"Native request timed out",code:2)
    }
    func check() async throws {
        try FileManager.default.createDirectory(at:output,withIntermediateDirectories:true)
        try Data("{\"binding\":\"key:90\"}".utf8).write(to:output.appendingPathComponent("quick-entry-binding.json"))
        web=WKWebView(frame:NSRect(x:0,y:0,width:1100,height:800))
        window=NSWindow(contentRect:web.frame,styleMask:[.titled,.resizable],backing:.buffered,defer:false)
        window.contentView=web
        web.load(URLRequest(url:URL(string:"http://127.0.0.1:8388/")!))
        try await wait(web,"document.querySelector('#verticals-command-bar') !== null")
        _ = try await js(web,"localStorage.setItem('vt-chat:last-model-selection',JSON.stringify({provider:'codex',model:'',effort:'medium',fast:false,permission:'read-only'}));true")
        entry=QuickEntry(state:output,base:URL(string:"http://127.0.0.1:8388/")!,web:web)
        entry.openMain = { self.window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps:true) }
        entry.show()
        try await wait(entry.entryWeb,"!!window.quickEntry")
        if CommandLine.arguments.contains("--partial") {
            entry.panel.orderOut(nil)
            entry=QuickEntry(state:output,base:URL(string:"http://127.0.0.1:8387/")!,web:web)
            entry.openMain = { self.window.makeKeyAndOrderFront(nil) }
            entry.show()
            try await wait(entry.entryWeb,"!!window.quickEntry")
            try await type("Задача уже сохранена")
            key(36,.command)
            try await settled()
            assert(entry.panel.isVisible && entry.panel.isKeyWindow,"Partial failure must keep retry focused")
            let text = try await js(entry.entryWeb,"document.querySelector('textarea').value") as? String
            assert(text == "Задача уже сохранена")
            try await picture(entry.entryWeb,"native-partial-error")
            print("Native partial failure opened saved task and kept retry focused")
            return
        }
        try await type("Быстрая заметка — новый бабл")
        try await Task.sleep(nanoseconds:300_000_000)
        try await picture(entry.entryWeb,"native-bubble")
        key(36)
        try await wait(entry.entryWeb,"document.querySelector('[role=status]').textContent === 'Added to Inbox'")
        assert(entry.panel.isVisible,"Success acknowledgement must be visible")
        try await picture(entry.entryWeb,"native-feedback-inbox")
        try await settled()
        assert(!entry.panel.isVisible,"Enter must save and close")
        print("Native Enter saved and closed")
        entry.show()
        entry.acknowledge("inbox")
        try await wait(entry.entryWeb,"document.querySelector('[role=status]').textContent === 'Added to Inbox'")
        entry.fadeConfirmation(entry.confirmation!)
        try await Task.sleep(nanoseconds:40_000_000)
        assert(entry.panel.isVisible && entry.panel.alphaValue > 0 && entry.panel.alphaValue < 1,"Window must fade through intermediate opacity")
        print("Native fade opacity:",entry.panel.alphaValue)
        entry.show()
        try await wait(entry.entryWeb,"!document.querySelector('textarea').readOnly && document.querySelector('[role=status]').textContent === ''")
        try await type("Keep the next thought")
        try await Task.sleep(nanoseconds:650_000_000)
        assert(entry.panel.isVisible && entry.panel.alphaValue == 1,"Previous fade must not hide a reopened capture")
        let next = try await js(entry.entryWeb,"document.querySelector('textarea').value") as? String
        assert(next == "Keep the next thought","New capture changed: \(String(describing:next))")
        print("Reopening cancels delayed close and preserves the next thought")
        entry.show()
        try await type("Отмена")
        key(53)
        try await Task.sleep(nanoseconds:200_000_000)
        assert(!entry.panel.isVisible,"Escape must close")
        print("Native Escape closed")
        if !CommandLine.arguments.contains("--input-only") {
        entry.show()
        try await type("Ответь только QUICK_BUBBLE_OK. Ничего не изменяй.")
        key(36,.command)
        try await settled()
        assert(!entry.panel.isVisible,"Command Enter must close after agent start")
        try await wait(web,"location.hash.startsWith('#goal/')")
        print("Agent opened task:",try await js(web,"location.hash"))
        try await Task.sleep(nanoseconds:2_000_000_000)
        try await picture(web,"native-agent-task")
        }
        // Actual network failure, not a mocked response.
        entry=QuickEntry(state:output,base:URL(string:"http://127.0.0.1:1/")!,web:web)
        entry.loading = true // This fixture loads UI from the live server but sends to a closed port.
        entry.entryWeb.load(URLRequest(url:URL(string:"http://127.0.0.1:8388/quick-entry.html")!))
        try await wait(entry.entryWeb,"!!window.quickEntry")
        entry.show()
        try await type("Текст остаётся при ошибке")
        key(36)
        try await settled()
        assert(entry.panel.isVisible)
        let text = try await js(entry.entryWeb,"document.querySelector('textarea').value") as? String
        assert(text == "Текст остаётся при ошибке")
        try await picture(entry.entryWeb,"native-error")
        print("Native failed request retained text; screenshots saved")
    }
}
