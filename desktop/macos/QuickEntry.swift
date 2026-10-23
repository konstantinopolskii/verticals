import Cocoa
import Carbon
import WebKit
import QuartzCore

final class EntryPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}
final class QuickEntry: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    let state: URL
    let base: URL
    let mainWeb: WKWebView
    var panel: EntryPanel!
    var entryWeb: WKWebView!
    var loaded = false
    var loading = false
    let loadingLabel = NSTextField(labelWithString: "Starting Quick Entry…")
    var openMain: (() -> Void)?
    var previous: NSRunningApplication?
    var busy = false
    var confirmation: UUID?
    var captureID = UUID().uuidString
    var captureText = ""
    var captureAction = ""
    var binding = "cmd+shift+key:49"
    var hotkey: EventHotKeyRef?
    var handler: EventHandlerRef?
    var globalMonitor: Any?
    var localMonitor: Any?
    var tap = ModifierTap(required: 6)
    var timer: Timer?
    var lastRequest = ""

    init(state: URL, base: URL, web: WKWebView) {
        self.state = state; self.base = base; self.mainWeb = web
        super.init()
        buildPanel()
        var type = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, _, pointer in
            guard let pointer else { return OSStatus(eventNotHandledErr) }
            let entry = Unmanaged<QuickEntry>.fromOpaque(pointer).takeUnretainedValue()
            entry.show(); return noErr
        }, 1, &type, Unmanaged.passUnretained(self).toOpaque(), &handler)
        let saved = read("quick-entry-binding.json")?["binding"] as? String ?? "cmd+shift+key:49"
        binding = saved
        let error = register(saved)
        status(request: "", error: error)
        timer = Timer.scheduledTimer(withTimeInterval: 0.3, repeats: true) { [weak self] _ in self?.poll() }
    }

    func read(_ name: String) -> [String: Any]? {
        guard let data = try? Data(contentsOf: state.appendingPathComponent(name)) else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }
    func write(_ name: String, _ value: [String: Any]) {
        try? FileManager.default.createDirectory(at: state, withIntermediateDirectories: true)
        if let data = try? JSONSerialization.data(withJSONObject: value) {
            try? data.write(to: state.appendingPathComponent(name), options: .atomic)
        }
    }
    func status(request: String, error: String?) {
        write("quick-entry-status.json", ["request": request, "binding": binding,
              "registered": hotkey != nil || globalMonitor != nil, "applied": error == nil, "error": error ?? "",
              "ui_ready": loaded, "accessibility": AXIsProcessTrusted(), "app_path": Bundle.main.bundlePath, "pid": ProcessInfo.processInfo.processIdentifier])
    }
    func poll() {
        if !binding.contains("key:") && globalMonitor != nil && !AXIsProcessTrusted() {
            if let globalMonitor { NSEvent.removeMonitor(globalMonitor) }
            if let localMonitor { NSEvent.removeMonitor(localMonitor) }
            globalMonitor = nil; localMonitor = nil
            status(request:lastRequest,error:"Accessibility is unavailable for this custom shortcut. Use the Quick Entry menu or ask the agent to change the shortcut.")
        }
        if !binding.contains("key:") && globalMonitor == nil && AXIsProcessTrusted() {
            status(request: lastRequest, error: register(binding))
        }
        guard let request = read("quick-entry-request.json"), let id = request["id"] as? String,
              id != lastRequest, let value = request["binding"] as? String else { return }
        lastRequest = id
        let error = register(value)
        if error == nil { write("quick-entry-binding.json", ["binding": binding]) }
        status(request: id, error: error)
    }
    func register(_ value: String) -> String? {
        if !value.contains("key:") && !AXIsProcessTrusted() {
            return "Modifier-only shortcuts need Accessibility access. Use the Quick Entry menu or choose a shortcut with a regular key."
        }
        if value == binding && (globalMonitor != nil || hotkey != nil) { return nil }
        var candidate: EventHotKeyRef?
        if value.contains("key:") {
            let parts = value.split(separator: "+").map(String.init)
            guard let last = parts.last, last.hasPrefix("key:"), let code = UInt32(last.dropFirst(4)), code <= 127 else {
                return "Unsupported key. Use fn or modifiers+key:code."
            }
            var mods: UInt32 = 0
            for part in parts.dropLast() {
                switch part {
                case "cmd": mods |= UInt32(cmdKey)
                case "ctrl": mods |= UInt32(controlKey)
                case "alt": mods |= UInt32(optionKey)
                case "shift": mods |= UInt32(shiftKey)
                default: return "Unsupported modifier"
                }
            }
            let result = RegisterEventHotKey(code, mods, EventHotKeyID(signature: 0x56545145, id: 1),
                                             GetApplicationEventTarget(), 0, &candidate)
            guard result == noErr else { return "Key registration failed (\(result)); previous binding kept." }
        }
        if let hotkey { UnregisterEventHotKey(hotkey) }
        if let globalMonitor { NSEvent.removeMonitor(globalMonitor) }
        if let localMonitor { NSEvent.removeMonitor(localMonitor) }
        hotkey = candidate; globalMonitor = nil; localMonitor = nil; binding = value; tap = ModifierTap(required: Self.mask(value))
        if !value.contains("key:") {
            globalMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.flagsChanged, .keyDown]) { [weak self] in self?.event($0) }
            localMonitor = NSEvent.addLocalMonitorForEvents(matching: [.flagsChanged, .keyDown]) { [weak self] event in
                self?.event(event); return event
            }
            if !AXIsProcessTrusted() { return "Modifier-only shortcuts need Accessibility access. Use the Quick Entry menu or choose a shortcut with a regular key." }
        }
        return nil
    }
    static func mask(_ binding: String) -> UInt {
        binding.split(separator: "+").reduce(0) { $0 | (["fn":UInt(1),"cmd":2,"shift":4,"ctrl":8,"alt":16][String($1)] ?? 0) }
    }
    func event(_ event: NSEvent) {
        if event.type == .keyDown { tap.key(); return }
        var mask: UInt = 0
        for (flag, bit): (NSEvent.ModifierFlags, UInt) in [(.function,1),(.command,2),(.shift,4),(.control,8),(.option,16)] {
            if event.modifierFlags.contains(flag) { mask |= bit }
        }
        if tap.flags(mask) { show() }
    }
    func buildPanel() {
        panel = EntryPanel(contentRect: NSRect(x: 0, y: 0, width: 600, height: 84),
                           styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = false
        let config = WKWebViewConfiguration()
        config.userContentController.add(self, name: "quickEntry")
        entryWeb = WKWebView(frame: NSRect(x:0,y:0,width:600,height:84), configuration:config)
        entryWeb.setValue(false, forKey:"drawsBackground")
        entryWeb.autoresizingMask = [.width, .height]
        entryWeb.navigationDelegate = self
        entryWeb.isHidden = true
        let content = NSView(frame:entryWeb.frame)
        content.wantsLayer = true
        content.layer?.backgroundColor = NSColor.black.cgColor
        content.layer?.cornerRadius = 42
        loadingLabel.frame = NSRect(x:32,y:24,width:536,height:36)
        loadingLabel.font = .systemFont(ofSize:28)
        loadingLabel.textColor = .white
        content.addSubview(loadingLabel)
        content.addSubview(entryWeb)
        panel.contentView = content
    }
    func loadIfNeeded() {
        guard !loaded, !loading else { return }
        loading = true
        entryWeb.load(URLRequest(url:base.appendingPathComponent("quick-entry.html"),cachePolicy:.reloadIgnoringLocalCacheData))
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        loaded = true; loading = false
        syncMotion()
        if var report = read("quick-entry-status.json") {
            report["ui_ready"] = true
            write("quick-entry-status.json",report)
        }
        loadingLabel.isHidden = true; entryWeb.isHidden = false
        panel.contentView?.layer?.backgroundColor = NSColor.clear.cgColor
        if panel.isVisible {
            panel.makeFirstResponder(entryWeb)
            entryWeb.evaluateJavaScript("window.quickEntry?.focus()",completionHandler:nil)
        }
    }
    func retryLoad() {
        loading = false
        guard panel.isVisible else { return }
        DispatchQueue.main.asyncAfter(deadline:.now()+0.5) { [weak self] in
            if self?.panel.isVisible == true { self?.loadIfNeeded() }
        }
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { retryLoad() }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { retryLoad() }
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? [String: Any], let action = body["action"] as? String else { return }
        if action == "resize", let height = body["height"] as? Double {
            let h = min(400, max(84, height))
            let frame = panel.frame
            panel.setFrame(NSRect(x:frame.minX,y:frame.maxY-h,width:frame.width,height:h),display:true)
        } else if action == "cancel" { close(cancel:true) }
        else if (action == "agent" || action == "inbox"), let text = body["text"] as? String { send(action, text:text) }
    }
    func ui(_ error: String = "", clear: Bool = false) {
        let args: [Any] = [busy,error,clear,captureAction]
        if let data = try? JSONSerialization.data(withJSONObject:args), let json = String(data:data,encoding:.utf8) {
            entryWeb.evaluateJavaScript("window.quickEntry?.state(..."+json+")", completionHandler:nil)
        }
    }
    func syncMotion() {
        let script: String
        if let choice = UserDefaults.standard.object(forKey:"ReduceMotion") as? Bool {
            script = "document.documentElement.setAttribute('data-reduce-motion','" + (choice ? "on" : "off") + "')"
        } else {
            script = "document.documentElement.removeAttribute('data-reduce-motion')"
        }
        entryWeb.evaluateJavaScript(script,completionHandler:nil)
    }
    @objc func show() {
        if confirmation != nil { confirmation = nil; ui(clear:true) }
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0
            panel.animator().alphaValue = 1
        }
        loadIfNeeded()
        if !panel.isVisible { previous = NSWorkspace.shared.frontmostApplication; panel.center() }
        panel.orderFrontRegardless(); panel.makeKey(); panel.makeFirstResponder(entryWeb)
        entryWeb.evaluateJavaScript("window.quickEntry?.focus()",completionHandler:nil)
    }
    func close(cancel: Bool, restore: Bool = true) {
        guard !busy else { return }
        confirmation = nil
        if cancel { captureID = UUID().uuidString; ui(clear:true) }
        panel.orderOut(nil)
        panel.alphaValue = 1
        if restore { previous?.activate(options: []) }
    }
    func fadeConfirmation(_ token: UUID) {
        guard confirmation == token else { return }
        let reduced = UserDefaults.standard.object(forKey:"ReduceMotion") as? Bool
            ?? NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        if reduced { close(cancel:true,restore:false); return }
        NSAnimationContext.runAnimationGroup({ context in
            context.duration = 0.12
            context.timingFunction = CAMediaTimingFunction(name:.easeOut)
            panel.animator().alphaValue = 0
        }, completionHandler:{ [weak self] in
            guard let self, self.confirmation == token else { return }
            self.close(cancel:true,restore:false)
        })
    }
    func acknowledge(_ action: String) {
        syncMotion()
        let token = UUID()
        confirmation = token
        captureID = UUID().uuidString
        // Confirmation stays in the same bubble; the completed action never waits for it.
        if action == "inbox" { panel.resignKey(); previous?.activate(options:[]) }
        let data = try! JSONSerialization.data(withJSONObject:[action])
        let args = String(data:data,encoding:.utf8)!
        entryWeb.evaluateJavaScript("window.quickEntry?.complete("+args+"[0])") { [weak self] _, _ in
            DispatchQueue.main.asyncAfter(deadline:.now()+0.20) {
                guard let self, self.confirmation == token else { return }
                self.fadeConfirmation(token)
            }
        }
    }
    func send(_ action: String, text raw: String) {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !busy, confirmation == nil, !text.isEmpty else { return }
        if text != captureText || action != captureAction {
            captureID = UUID().uuidString; captureText = text; captureAction = action
        }
        busy = true; ui()
        mainWeb.evaluateJavaScript("JSON.parse(localStorage.getItem('vt-chat:last-model-selection') || 'null')") { [weak self] selection, _ in
            guard let self else { return }
            var body: [String: Any] = ["request": self.captureID, "action": action, "text": text]
            if let selection = selection as? [String: Any] { body["settings"] = selection }
            var request = URLRequest(url: self.base.appendingPathComponent("__chat/quick-entry"))
            request.httpMethod = "POST"; request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: body); request.timeoutInterval = 30
            URLSession.shared.dataTask(with: request) { data, response, error in
                let result = data.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any] ?? [:]
                DispatchQueue.main.async {
                    self.busy = false
                    guard (response as? HTTPURLResponse)?.statusCode == 200, error == nil else {
                        self.ui(result["error"] as? String ?? "Could not send. Your text is saved — try again.")
                        return
                    }
                    if action == "agent", let goal = result["goal"] as? String {
                        let path = "#goal/" + goal
                        let encoded = try! JSONSerialization.data(withJSONObject:[path])
                        let args = String(data:encoded,encoding:.utf8)!
                        self.mainWeb.evaluateJavaScript("history.pushState(null,'',"+args+"[0]);window.dispatchEvent(new PopStateEvent('popstate'))",completionHandler:nil)
                        self.openMain?()
                    }
                    if let error = result["error"] as? String {
                        self.ui("Task saved. " + error + " Press ⌘Enter to retry the agent.")
                        self.show()
                        return
                    }
                    let event: [String: Any] = ["result": result, "text": text, "selection": selection ?? NSNull()]
                    if let json = try? JSONSerialization.data(withJSONObject: event), let value = String(data: json, encoding: .utf8) {
                        self.mainWeb.evaluateJavaScript("window.dispatchEvent(new CustomEvent('verticals-quick-entry', {detail: \(value)}))", completionHandler: nil)
                    }
                    self.acknowledge(action)
                }
            }.resume()
        }
    }
}
