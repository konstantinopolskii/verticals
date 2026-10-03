// Verticals.app: a native window (WKWebView) around the desktop launcher.
// On launch it starts Resources/desktop/launcher.py with the bundled Python (PostgreSQL, API, MCP,
// UI gateway) unless Verticals is already running, waits until it is healthy, and shows the UI.
// Quitting stops what it started. Resources mirrors the repository layout (see desktop/macos/bundle.py).
// Updates come from the repository's GitHub releases (Updater.swift, UpdateIndicator.swift).
import Cocoa
import WebKit

let uiURL = URL(string: "http://127.0.0.1:8288/")!
let healthURL = URL(string: "http://127.0.0.1:8288/healthz")!
let busyURL = URL(string: "http://127.0.0.1:8288/__chat/busy")!
// `-ReleasesAPI <url>` on the command line points the updater elsewhere (tests).
let releasesAPI = URL(string: UserDefaults.standard.string(forKey: "ReleasesAPI")
    ?? "https://api.github.com/repos/konstantinopolskii/verticals/releases/latest")!

// The page runs under the transparent title bar, which leaves the press there to the page; this
// gives it back to the window: drag moves it, double click acts as the system setting says.
final class WebView: WKWebView {
    override func mouseDown(with event: NSEvent) {
        guard let window, event.locationInWindow.y > window.contentLayoutRect.maxY else {
            return super.mouseDown(with: event)
        }
        guard event.clickCount == 2 else { return window.performDrag(with: event) }
        switch UserDefaults.standard.string(forKey: "AppleActionOnDoubleClick") {
        case "Minimize": window.miniaturize(nil)
        case "None": break
        default: window.zoom(nil)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var webView: WebView!
    var status: NSTextField!
    var backend: Process?
    var updater: Updater!
    var indicator: UpdateIndicator!
    var relaunching = false

    // Code, Python and PostgreSQL live in Contents/Resources; data in ~/Library/Application Support.
    var resources: URL { Bundle.main.resourceURL! }
    var root: URL { resources }
    // `-StateDir <path>` on the command line keeps a test run away from the real data.
    var stateDir: URL {
        UserDefaults.standard.string(forKey: "StateDir").map { URL(fileURLWithPath: $0) }
            ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("Verticals")
    }
    var logPath: String { stateDir.appendingPathComponent("app.log").path }

    func applicationDidFinishLaunching(_ note: Notification) {
        // The last quit's install opens Verticals when it is done; a Restart lost to a crash installs now.
        if Updater.installing(stateDir) { exit(0) }
        updater = Updater(stateDir: stateDir)
        if updater.launch() {
            updater.installOnQuit(relaunch: true)
            exit(0)
        }
        buildMenu()
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        webView = WebView(frame: .zero, configuration: config)
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
                          styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                          backing: .buffered, defer: false)
        window.title = "Verticals"
        // The page shows through the title bar, only the window buttons stay; the UI has no dark theme.
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.titlebarSeparatorStyle = .none
        window.backgroundColor = .white
        window.appearance = NSAppearance(named: .aqua)
        window.contentView = content
        window.setFrameAutosaveName("VerticalsWindow")
        if !window.setFrameUsingName("VerticalsWindow") { window.center() }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        syncTitlebar()
        for name in [NSWindow.didEnterFullScreenNotification, NSWindow.didExitFullScreenNotification] {
            NotificationCenter.default.addObserver(forName: name, object: window, queue: .main) { _ in self.syncTitlebar() }
        }

        healthy { up in
            if up { self.showUI() } else { self.startBackend() }
        }
        indicator = UpdateIndicator(window: window, updater: updater)
        indicator.restart = { [unowned self] in restartToUpdate() }
        indicator.cancelRestart = { [unowned self] in
            updater.update { $0.restart = false }
            updater.activity = .none
        }
        updater.changed = { [unowned self] in indicator.refresh() }
        updater.reveal = { [unowned self] in indicator.reveal() }
        updater.start()
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
                                                 withIntermediateDirectories: true,
                                                 attributes: [.posixPermissions: 0o700])
        FileManager.default.createFile(atPath: logURL.path, contents: nil,
                                       attributes: [.posixPermissions: 0o600])
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
        let reopen = UserDefaults.standard.string(forKey: "ReopenPage").flatMap { URL(string: $0) }
        UserDefaults.standard.removeObject(forKey: "ReopenPage")
        let page = reopen.flatMap { $0.host == uiURL.host && $0.port == uiURL.port ? $0 : nil } ?? uiURL
        webView.load(URLRequest(url: page))
    }

    func fail(_ message: String) {
        webView.isHidden = true
        status.isHidden = false
        status.stringValue = message
    }

    var quitting = false

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if quitting { return .terminateLater }
        quitting = true
        Task {
            await savePage()
            if let process = backend, process.isRunning {
                // SIGTERM makes the launcher stop the services and shut PostgreSQL down cleanly.
                status.stringValue = "Stopping Verticals…"
                status.isHidden = false
                webView.isHidden = true
                process.terminate()
                await withCheckedContinuation { (done: CheckedContinuation<Void, Never>) in
                    DispatchQueue.global().async {
                        let deadline = Date().addingTimeInterval(20)
                        while process.isRunning && Date() < deadline { usleep(100_000) }
                        done.resume()
                    }
                }
            }
            updater.installOnQuit(relaunch: relaunching)
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }

    // Edits still waiting out their debounce reach the API before it stops; a restart reopens this page.
    func savePage() async {
        guard webView != nil, !webView.isHidden else { return }
        if relaunching, let url = webView.url, url.host == uiURL.host, url.port == uiURL.port {
            UserDefaults.standard.set(url.absoluteString, forKey: "ReopenPage")
        }
        await withCheckedContinuation { (done: CheckedContinuation<Void, Never>) in
            var finished = false
            let finish = {
                if !finished { finished = true; done.resume() }
            }
            webView.callAsyncJavaScript("await window.verticalsBeforeQuit?.()", arguments: [:], in: nil, in: .page) { _ in finish() }
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) { finish() }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    // MARK: updates

    @objc func checkForUpdatesNow(_ sender: Any?) { Task { await updater.check(manual: true) } }

    // Restart waits while an agent is answering, then quits with the relaunch flag set.
    func restartToUpdate() {
        updater.update { $0.restart = true; $0.failure = nil }
        waitForAgent()
    }

    func waitForAgent(unanswered: Int = 0) {
        var request = URLRequest(url: busyURL)
        request.timeoutInterval = 2
        URLSession.shared.dataTask(with: request) { data, _, _ in
            let busy = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }?["busy"] as? Bool
            DispatchQueue.main.async {
                guard self.updater.state.restart else { return }
                func askAgain(_ count: Int) {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 2) { self.waitForAgent(unanswered: count) }
                }
                switch busy {
                case true?:
                    self.updater.activity = .waitingForAgent
                    askAgain(0)
                case nil where unanswered < 3:
                    // No answer is not "free": ask again before restarting over a running agent.
                    askAgain(unanswered + 1)
                default:
                    self.relaunching = true
                    // From the run loop, not this main-queue block: termination waits for a main-queue reply.
                    NSApp.perform(#selector(NSApplication.terminate(_:)), with: nil, afterDelay: 0)
                }
            }
        }.resume()
    }

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

    // The page keeps its content below the title bar by `--titlebar-height`; full screen has none.
    func syncTitlebar() {
        let height = window.styleMask.contains(.fullScreen) ? 0 : window.frame.height - window.contentLayoutRect.height
        let js = "document.documentElement.style.setProperty('--titlebar-height', '\(Int(height))px')"
        let scripts = webView.configuration.userContentController
        scripts.removeAllUserScripts()
        scripts.addUserScript(WKUserScript(source: js, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        webView.evaluateJavaScript(js)
    }

    // MARK: menu (Edit is what makes copy/paste work inside the web view)

    func buildMenu() {
        let main = NSMenu()
        func item(_ title: String, _ action: Selector?, _ key: String, _ mods: NSEvent.ModifierFlags = .command) -> NSMenuItem {
            let i = NSMenuItem(title: title, action: action, keyEquivalent: key)
            i.keyEquivalentModifierMask = mods
            return i
        }
        let app = NSMenu()
        let updates = item("Check for Updates…", #selector(checkForUpdatesNow(_:)), "")
        updates.target = self
        app.addItem(updates)
        app.addItem(.separator())
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

@main enum Main {
    static func main() {
        let args = CommandLine.arguments
        if let at = args.firstIndex(of: "--install-update") { Installer.run(Array(args[(at + 1)...])) }
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        app.run()
    }
}
