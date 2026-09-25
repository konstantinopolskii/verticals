// Verticals.app: a native window (WKWebView) around the desktop launcher.
// On launch it starts Resources/desktop/launcher.py with the bundled Python (PostgreSQL, API, MCP,
// UI gateway) unless Verticals is already running, waits until it is healthy, and shows the UI.
// Quitting stops what it started. Resources mirrors the repository layout (see desktop/macos/bundle.py).
import Cocoa
import WebKit

let uiURL = URL(string: "http://127.0.0.1:8288/")!
let healthURL = URL(string: "http://127.0.0.1:8288/healthz")!

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var status: NSTextField!
    var backend: Process?

    // Code, Python and PostgreSQL live in Contents/Resources; data in ~/Library/Application Support.
    var resources: URL { Bundle.main.resourceURL! }
    var root: URL { resources }
    var stateDir: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Verticals")
    }
    var logPath: String { stateDir.appendingPathComponent("app.log").path }

    func applicationDidFinishLaunching(_ note: Notification) {
        buildMenu()
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.isHidden = true

        status = NSTextField(labelWithString: "Starting Verticals…")
        status.font = .systemFont(ofSize: 15)
        status.textColor = .secondaryLabelColor
        status.alignment = .center

        let content = NSView()
        for view in [webView!, status!] as [NSView] {
            view.translatesAutoresizingMaskIntoConstraints = false
            content.addSubview(view)
        }
        NSLayoutConstraint.activate([
            webView.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            webView.topAnchor.constraint(equalTo: content.topAnchor),
            webView.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            status.centerXAnchor.constraint(equalTo: content.centerXAnchor),
            status.centerYAnchor.constraint(equalTo: content.centerYAnchor),
            status.widthAnchor.constraint(lessThanOrEqualTo: content.widthAnchor, constant: -40),
        ])

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1320, height: 860),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "Verticals"
        window.contentView = content
        window.setFrameAutosaveName("VerticalsWindow")
        if !window.setFrameUsingName("VerticalsWindow") { window.center() }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        healthy { up in
            if up { self.showUI() } else { self.startBackend() }
        }
    }

    // MARK: backend

    func healthy(_ done: @escaping (Bool) -> Void) {
        var request = URLRequest(url: healthURL)
        request.timeoutInterval = 1
        URLSession.shared.dataTask(with: request) { data, response, _ in
            let ok = (response as? HTTPURLResponse)?.statusCode == 200
                && (data.flatMap { String(data: $0, encoding: .utf8) }?.contains("\"db\":\"ok\"") ?? false)
            DispatchQueue.main.async { done(ok) }
        }.resume()
    }

    func startBackend() {
        let script = root.appendingPathComponent("desktop/launcher.py")
        guard FileManager.default.fileExists(atPath: script.path) else {
            return fail("This build is incomplete: desktop/launcher.py is missing from the app.")
        }
        let process = Process()
        let res = resources.path
        process.executableURL = URL(fileURLWithPath: "\(res)/python/bin/python3")
        process.arguments = [script.path]
        process.currentDirectoryURL = root
        // Apps launched from Finder get a bare PATH; the agent CLIs (claude, codex) live in these.
        var env = ProcessInfo.processInfo.environment
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        env["PATH"] = ["\(home)/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin",
                       "/usr/sbin", "/sbin"].joined(separator: ":")
        env["VERTICALS_DESKTOP_STATE"] = stateDir.path
        env["VERTICALS_DESKTOP_PYTHONPATH"] = "\(res):\(res)/site"
        env["VERTICALS_PG_BIN"] = (try? String(contentsOf: resources.appendingPathComponent("pg/BINDIR"), encoding: .utf8))
            .map { "\(res)/pg/" + $0.trimmingCharacters(in: .whitespacesAndNewlines) } ?? ""
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONNOUSERSITE"] = "1"
        process.environment = env
        let logURL = URL(fileURLWithPath: logPath)
        try? FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(),
                                                 withIntermediateDirectories: true)
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        let log = try? FileHandle(forWritingTo: logURL)
        process.standardOutput = log
        process.standardError = log
        process.terminationHandler = { p in
            DispatchQueue.main.async {
                if self.backend === p && !self.quitting {
                    self.fail("Verticals stopped (exit \(p.terminationStatus)). See \(self.logPath).")
                }
            }
        }
        do {
            try process.run()
        } catch {
            return fail("Could not start Verticals: \(error.localizedDescription)")
        }
        backend = process
        status.stringValue = "Starting Verticals… (the first launch sets up the database, about a minute)"
        waitForBackend(attempts: 240)
    }

    func waitForBackend(attempts: Int) {
        healthy { up in
            if up { return self.showUI() }
            guard attempts > 0, self.backend?.isRunning == true else {
                return self.fail("Verticals did not start. See \(self.logPath).")
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.waitForBackend(attempts: attempts - 1) }
        }
    }

    func showUI() {
        status.isHidden = true
        webView.isHidden = false
        webView.load(URLRequest(url: uiURL))
    }

    func fail(_ message: String) {
        webView.isHidden = true
        status.isHidden = false
        status.stringValue = message
    }

    var quitting = false

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let process = backend, process.isRunning else { return .terminateNow }
        // SIGTERM makes start.py stop the services and shut PostgreSQL down cleanly.
        quitting = true
        status.stringValue = "Stopping Verticals…"
        status.isHidden = false
        webView.isHidden = true
        process.terminate()
        DispatchQueue.global().async {
            let deadline = Date().addingTimeInterval(20)
            while process.isRunning && Date() < deadline { usleep(100_000) }
            DispatchQueue.main.async { sender.reply(toApplicationShouldTerminate: true) }
        }
        return .terminateLater
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    // MARK: web view

    // Links that leave the app (target=_blank or another origin) open in the default browser.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { NSWorkspace.shared.open(url) }
        return nil
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = action.request.url, url.host != uiURL.host || url.port != uiURL.port,
           action.navigationType == .linkActivated {
            NSWorkspace.shared.open(url)
            return decisionHandler(.cancel)
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.runModal()
        completionHandler()
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")
        completionHandler(alert.runModal() == .alertFirstButtonReturn)
    }

    @objc func reload(_ sender: Any?) { webView.reload() }

    // MARK: menu (Edit is what makes copy/paste work inside the web view)

    func buildMenu() {
        let main = NSMenu()
        func item(_ title: String, _ action: Selector?, _ key: String, _ mods: NSEvent.ModifierFlags = .command) -> NSMenuItem {
            let i = NSMenuItem(title: title, action: action, keyEquivalent: key)
            i.keyEquivalentModifierMask = mods
            return i
        }
        let app = NSMenu()
        app.addItem(item("Hide Verticals", #selector(NSApplication.hide(_:)), "h"))
        app.addItem(.separator())
        app.addItem(item("Quit Verticals", #selector(NSApplication.terminate(_:)), "q"))
        let edit = NSMenu(title: "Edit")
        edit.addItem(item("Undo", Selector(("undo:")), "z"))
        edit.addItem(item("Redo", Selector(("redo:")), "z", [.command, .shift]))
        edit.addItem(.separator())
        edit.addItem(item("Cut", #selector(NSText.cut(_:)), "x"))
        edit.addItem(item("Copy", #selector(NSText.copy(_:)), "c"))
        edit.addItem(item("Paste", #selector(NSText.paste(_:)), "v"))
        edit.addItem(item("Select All", #selector(NSText.selectAll(_:)), "a"))
        let view = NSMenu(title: "View")
        let reloadItem = item("Reload", #selector(reload(_:)), "r")
        reloadItem.target = self
        view.addItem(reloadItem)
        view.addItem(item("Enter Full Screen", #selector(NSWindow.toggleFullScreen(_:)), "f", [.command, .control]))
        let win = NSMenu(title: "Window")
        win.addItem(item("Minimize", #selector(NSWindow.miniaturize(_:)), "m"))
        win.addItem(item("Close", #selector(NSWindow.performClose(_:)), "w"))
        for (title, menu) in [("Verticals", app), ("Edit", edit), ("View", view), ("Window", win)] {
            let top = NSMenuItem(title: title, action: nil, keyEquivalent: "")
            top.submenu = menu
            main.addItem(top)
        }
        NSApp.mainMenu = main
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
