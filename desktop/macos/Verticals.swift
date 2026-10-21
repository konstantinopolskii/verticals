// Verticals.app: a native window (WKWebView) around the desktop launcher.
// On launch it starts Resources/desktop/launcher.py with the bundled Python (PostgreSQL, API, MCP,
// UI gateway) unless Verticals is already running, waits until it is healthy, and shows the UI.
// Closing the window keeps everything running behind the menu bar icon, so agents keep the board and
// MCP; Quit stops what it started. Resources mirrors the repository layout (see desktop/macos/bundle.py).
// Updates come from the repository's GitHub releases (Updater.swift, UpdateIndicator.swift).
import Cocoa
import ServiceManagement
import WebKit

let uiURL = URL(string: "http://127.0.0.1:8288/")!
let healthURL = URL(string: "http://127.0.0.1:8288/healthz")!
let busyURL = URL(string: "http://127.0.0.1:8288/__chat/busy")!
let mcpURL = "http://127.0.0.1:8281/mcp"
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

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, NSMenuDelegate, WKNavigationDelegate, WKUIDelegate,
                         WKScriptMessageHandler {
    var window: NSWindow!
    var webView: WebView!
    var status: NSTextField!
    var backend: Process?
    var updater: Updater!
    var indicator: UpdateIndicator!
    var relaunching = false
    var tray: NSStatusItem!
    var serving = false
    // Opened at login or relaunched by an update made while the window was closed: menu bar only.
    var startHidden = false
    var hideAfterFullScreen = false

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

    func applicationWillFinishLaunching(_ note: Notification) {
        let event = NSAppleEventManager.shared().currentAppleEvent
        startHidden = UserDefaults.standard.bool(forKey: "StartHidden")
            || event?.paramDescriptor(forKeyword: keyAEPropData)?.enumCodeValue == keyAELaunchedAsLogInItem
        NSApp.setActivationPolicy(startHidden ? .accessory : .regular)
    }

    func applicationDidFinishLaunching(_ note: Notification) {
        // The last quit's install opens Verticals when it is done; a Restart lost to a crash installs now.
        if Updater.installing(stateDir) { exit(0) }
        updater = Updater(stateDir: stateDir)
        if updater.launch() {
            updater.installOnQuit(relaunch: true)
            exit(0)
        }
        buildMenu()
        buildTray()
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        config.userContentController.add(self, name: "zoom")
        webView = WebView(frame: .zero, configuration: config)
        webView.underPageBackgroundColor = .windowBackgroundColor
        let zoom = UserDefaults.standard.double(forKey: "PageZoom")
        if zoom > 0 { webView.pageZoom = zoom }
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
        // The page shows through the title bar; appearance is inherited from macOS.
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.titlebarSeparatorStyle = .none
        window.backgroundColor = .windowBackgroundColor
        window.contentView = content
        window.delegate = self
        window.isReleasedWhenClosed = false
        window.setFrameAutosaveName("VerticalsWindow")
        if !window.setFrameUsingName("VerticalsWindow") { window.center() }
        if !startHidden {
            window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
        }
        syncTitlebar()
        for name in [NSWindow.didEnterFullScreenNotification, NSWindow.didExitFullScreenNotification] {
            NotificationCenter.default.addObserver(forName: name, object: window, queue: .main) { _ in
                self.syncTitlebar()
                if self.hideAfterFullScreen && !self.window.styleMask.contains(.fullScreen) {
                    self.hideAfterFullScreen = false
                    self.hideWindow()
                }
            }
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
        updater.changed = { [unowned self] in
            indicator.refresh()
            installWhenIdle()
        }
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
        var env = ProcessInfo.processInfo.environment.merging(agentEnvironment) { _, chosen in chosen }
        env["PATH"] = agentPath
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
        serving = true
        tray.button?.appearsDisabled = false
        status.isHidden = true
        webView.isHidden = false
        let reopen = UserDefaults.standard.string(forKey: "ReopenPage").flatMap { URL(string: $0) }
        UserDefaults.standard.removeObject(forKey: "ReopenPage")
        // A task's link that came while the board was starting is where it opens.
        let task = pendingTask.flatMap { AppLinks.boardURL(task: $0, ui: uiURL) }
        pendingTask = nil
        let page = task ?? reopen.flatMap { $0.host == uiURL.host && $0.port == uiURL.port ? $0 : nil } ?? uiURL
        webView.load(URLRequest(url: page))
    }

    // MARK: a task's link

    // `verticals://goal/<id>` (docs/design/task-sessions.md): a session begun for a task starts with it, Terminal and Codex show it
    // as a link, and a click comes here. The window comes forward and the board opens that task; before the board is up the link
    // waits for it, and a link in the page itself comes here directly.
    var pendingTask: String?

    func application(_ application: NSApplication, open urls: [URL]) {
        guard let id = urls.lazy.compactMap({ AppLinks.taskID($0) }).first else { return }
        openTask(id)
    }

    func openTask(_ id: String) {
        pendingTask = id
        guard window != nil else { return }  // still launching: showUI opens it
        if window.isVisible { NSApp.activate(ignoringOtherApps: true) } else { showWindow(nil) }
        showPendingTask()
    }

    // On the board's own page the address only changes after `#` (the page opens the task, and Back returns); anywhere else the
    // board loads at the task's address.
    func showPendingTask() {
        guard serving, let id = pendingTask else { return }
        pendingTask = nil
        if let url = webView.url, url.host == uiURL.host, url.port == uiURL.port, !webView.isLoading {
            webView.callAsyncJavaScript("location.hash = fragment", arguments: ["fragment": AppLinks.fragment(task: id)],
                                        in: nil, in: .page, completionHandler: nil)
        } else if let target = AppLinks.boardURL(task: id, ui: uiURL) {
            webView.load(URLRequest(url: target))
        }
    }

    func fail(_ message: String) {
        serving = false
        tray.button?.appearsDisabled = true
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
            updater.installOnQuit(relaunch: relaunching, hidden: !window.isVisible)
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

    // MARK: window and menu bar icon

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if window.styleMask.contains(.fullScreen) {
            hideAfterFullScreen = true
            window.toggleFullScreen(nil)
        } else {
            hideWindow()
        }
        return false
    }

    func hideWindow() {
        window.orderOut(nil)
        NSApp.setActivationPolicy(.accessory)
        installWhenIdle()
    }

    @objc func showWindow(_ sender: Any?) {
        NSApp.setActivationPolicy(.regular)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        if !window.isVisible { showWindow(nil) }
        return false
    }

    func buildTray() {
        tray = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        tray.button?.image = Self.mascot()
        tray.button?.toolTip = "Verticals"
        tray.button?.appearsDisabled = true
        tray.menu = NSMenu()
        tray.menu?.delegate = self
    }

    // The app icon's mascot as a menu bar template: a disc with its line cut out.
    static func mascot() -> NSImage {
        let image = NSImage(size: NSSize(width: 18, height: 18), flipped: false) { _ in
            NSColor.black.setFill()
            NSBezierPath(ovalIn: NSRect(x: 2, y: 2, width: 14, height: 14)).fill()
            NSGraphicsContext.current?.compositingOperation = .destinationOut
            NSBezierPath(roundedRect: NSRect(x: 8.2, y: 5.6, width: 1.6, height: 6.8), xRadius: 0.8, yRadius: 0.8).fill()
            return true
        }
        image.isTemplate = true
        return image
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        func item(_ title: String, _ action: Selector?) -> NSMenuItem {
            let i = NSMenuItem(title: title, action: action, keyEquivalent: "")
            i.target = self
            return i
        }
        menu.addItem(item("Open Verticals", #selector(showWindow(_:))))
        menu.addItem(.separator())
        let state = item(serving ? "Board and MCP are running" : backend?.isRunning == true ? "Starting…" : "Stopped, see app.log", nil)
        state.isEnabled = false
        menu.addItem(state)
        // The click is the consent: nothing is written into Claude Code's or Codex's settings before it. The tick says it was done here.
        let ready = serving && FileManager.default.fileExists(atPath: mcpHeaders.path)
        let claudeItem = item("Use Verticals in Claude Code", ready ? #selector(connectClaude(_:)) : nil)
        claudeItem.state = UserDefaults.standard.bool(forKey: Self.inClaudeCode) ? .on : .off
        claudeItem.toolTip = "Adds Verticals to Claude Code in every folder, as the \(AppLinks.claudeServer) MCP server (claude mcp add-json --scope user)"
        menu.addItem(claudeItem)
        let codexItem = item("Use Verticals in Codex", ready ? #selector(connectCodex(_:)) : nil)
        codexItem.state = UserDefaults.standard.bool(forKey: Self.inCodex) ? .on : .off
        codexItem.toolTip = "Adds Verticals to Codex, as the \(AppLinks.codexServer) MCP server (codex mcp add)"
        menu.addItem(codexItem)
        let login = item("Open at Login", #selector(toggleLogin(_:)))
        switch SMAppService.mainApp.status {
        case .enabled: login.state = .on
        case .requiresApproval: login.title = "Open at Login (allow in System Settings)"
        default: break
        }
        menu.addItem(login)
        menu.addItem(.separator())
        menu.addItem(item("Check for Updates…", #selector(checkForUpdatesNow(_:))))
        menu.addItem(item("Quit Verticals", #selector(NSApplication.terminate(_:))))
    }

    @objc func toggleLogin(_ sender: Any?) {
        let service = SMAppService.mainApp
        do {
            switch service.status {
            case .enabled: try service.unregister()
            case .requiresApproval: SMAppService.openSystemSettingsLoginItems()
            default: try service.register()
            }
        } catch {
            NSApp.activate(ignoringOtherApps: true)
            NSAlert(error: error).runModal()
        }
    }

    // Claude Code reads the token from the owner-only file the launcher writes, never from its own config.
    var mcpHeaders: URL { stateDir.appendingPathComponent("mcp-headers.json") }

    static let inClaudeCode = "VerticalsInClaudeCode", inCodex = "VerticalsInCodex"

    @objc func connectClaude(_ sender: Any?) {
        guard let add = AppLinks.claudeAddArguments(mcpURL: mcpURL, headersFile: mcpHeaders.path) else { return }
        connect("Claude Code", tool: "claude", key: Self.inClaudeCode, remove: AppLinks.claudeRemoveArguments, add: add,
                done: "New Claude Code sessions in any folder can use the board through the \(AppLinks.claudeServer) MCP server while Verticals runs.")
    }

    @objc func connectCodex(_ sender: Any?) {
        let python = resources.appendingPathComponent("python/bin/python3").path
        let relay = root.appendingPathComponent("desktop/chat/mcp_proxy.py").path
        connect("Codex", tool: "codex", key: Self.inCodex, remove: AppLinks.codexRemoveArguments,
                add: AppLinks.codexAddArguments(python: python, relay: relay, mcpURL: mcpURL, headersFile: mcpHeaders.path),
                done: "New Codex sessions can use the board through the \(AppLinks.codexServer) MCP server while Verticals runs.")
    }

    // Replaces an earlier connection under the same name, then says what happened; the tick is kept for the menu.
    func connect(_ name: String, tool: String, key: String, remove: [String], add: [String], done: String) {
        Task {
            _ = await agent(tool, remove)
            let (code, output) = await agent(tool, add)
            UserDefaults.standard.set(code == 0, forKey: key)
            let alert = NSAlert()
            if code == 0 {
                alert.messageText = "\(name) is connected"
                alert.informativeText = done
            } else {
                alert.messageText = "Couldn't connect \(name)"
                alert.informativeText = code == 127 ? "The \(tool) command isn't installed." : output
            }
            NSApp.activate(ignoringOtherApps: true)
            alert.runModal()
        }
    }

    func agent(_ tool: String, _ args: [String]) async -> (Int32, String) {
        await withCheckedContinuation { done in
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            process.arguments = [tool] + args
            var env = ProcessInfo.processInfo.environment.merging(agentEnvironment) { _, chosen in chosen }
            env["PATH"] = agentPath
            process.environment = env
            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = pipe
            process.terminationHandler = { p in
                let output = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                done.resume(returning: (p.terminationStatus, output.trimmingCharacters(in: .whitespacesAndNewlines)))
            }
            do { try process.run() } catch { done.resume(returning: (127, "")) }
        }
    }

    // Whose sign-in Claude Code and Codex use: `agents.env` in the state folder (AppLinks.agentEnvironment).
    var agentEnvironment: [String: String] {
        let file = stateDir.appendingPathComponent("agents.env")
        guard let text = try? String(contentsOf: file, encoding: .utf8) else { return [:] }
        return AppLinks.agentEnvironment(text, home: FileManager.default.homeDirectoryForCurrentUser.path)
    }

    // Apps launched from Finder get a bare PATH; the agent CLIs (claude, codex) live in these.
    var agentPath: String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return ["\(home)/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
            .joined(separator: ":")
    }

    // MARK: updates

    // The answer comes in the title bar, so a check from the menu bar icon opens the window.
    @objc func checkForUpdatesNow(_ sender: Any?) {
        if !window.isVisible { showWindow(nil) }
        Task { await updater.check(manual: true) }
    }

    // With the window closed nobody sees the Update button: a downloaded update installs once no agent
    // is answering, and Verticals comes back to the menu bar. A failed install waits for Restart.
    var idleCheck = false

    func installWhenIdle() {
        guard !idleCheck, !quitting, !window.isVisible, updater.readyToInstall, updater.blocked == nil,
              updater.state.failure == nil, !updater.state.restart else { return }
        idleCheck = true
        var request = URLRequest(url: busyURL)
        request.timeoutInterval = 2
        URLSession.shared.dataTask(with: request) { data, _, _ in
            let busy = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }?["busy"] as? Bool
            DispatchQueue.main.async {
                self.idleCheck = false
                guard busy == false else {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 60) { self.installWhenIdle() }
                    return
                }
                guard !self.window.isVisible, !self.quitting else { return }
                self.relaunching = true
                NSApp.perform(#selector(NSApplication.terminate(_:)), with: nil, afterDelay: 0)
            }
        }.resume()
    }

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
        if let url = action.request.url {
            if let id = AppLinks.taskID(url) { openTask(id) } else { NSWorkspace.shared.open(url) }
        }
        return nil
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = action.request.url, let id = AppLinks.taskID(url) {
            openTask(id)
            return decisionHandler(.cancel)
        }
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

    // Match the developer panel's browser-style steps; both controls keep the same PageZoom preference.
    private static let zoomSteps: [Double] = [0.5, 0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2]

    func setPageZoom(_ value: Double) {
        guard value.isFinite else { return }
        webView.pageZoom = min(max(value, 0.5), 2)
        UserDefaults.standard.set(webView.pageZoom, forKey: "PageZoom")
        syncTitlebar()
    }

    @objc func zoomIn(_ sender: Any?) {
        if let next = Self.zoomSteps.first(where: { $0 > Double(webView.pageZoom) + 0.001 }) {
            setPageZoom(next)
        }
    }

    @objc func zoomOut(_ sender: Any?) {
        if let next = Self.zoomSteps.reversed().first(where: { $0 < Double(webView.pageZoom) - 0.001 }) {
            setPageZoom(next)
        }
    }

    @objc func actualSize(_ sender: Any?) { setPageZoom(1) }

    // The developer panel uses the same native zoom as the View menu and its shortcuts.
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "zoom", let value = (message.body as? NSNumber)?.doubleValue else { return }
        setPageZoom(value)
    }

    // The page keeps its content below the title bar by `--titlebar-height`, in its own zoomed pixels; full screen has
    // none. `verticalsPageZoom` tells the dev panel's zoom buttons where they start. The Reduce Motion answer rides in
    // the same script (below), because this call replaces every user script.
    func syncTitlebar() {
        let height = window.styleMask.contains(.fullScreen) ? 0 : window.frame.height - window.contentLayoutRect.height
        let js = "document.documentElement.style.setProperty('--titlebar-height', '\(Int((height / webView.pageZoom).rounded()))px');"
            + "window.verticalsPageZoom = \(webView.pageZoom);"
            + reduceMotionScript
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
        view.addItem(.separator())
        for (title, action, key) in [("Zoom In", #selector(zoomIn(_:)), "+"),
                                     ("Zoom Out", #selector(zoomOut(_:)), "-"),
                                     ("Actual Size", #selector(actualSize(_:)), "0")] {
            let command = item(title, action, key)
            command.target = self
            view.addItem(command)
        }
        // Browsers also accept the unshifted equals key on keyboards where + shares that key.
        let equals = item("Zoom In", #selector(zoomIn(_:)), "=")
        equals.target = self
        equals.isHidden = true
        equals.allowsKeyEquivalentWhenHidden = true
        view.addItem(equals)
        view.addItem(.separator())
        let motionItem = item("Reduce Motion", #selector(toggleReduceMotion(_:)), "")
        motionItem.target = self
        view.addItem(motionItem)
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

// MARK: Reduce Motion (View menu), docs/design/column-bounce.md
//
// The checkmark shows macOS's own Reduce motion until the person clicks it; from then on it shows their choice, kept in the
// app's defaults (`ReduceMotion`). A web view can't be told to change what it reads from macOS, so the app puts its answer
// on <html> as `data-reduce-motion`, "on" or "off", from the start of every page and now (`syncTitlebar` sends it). With no
// choice made it puts nothing there and the page asks macOS itself, as a browser does. Everything in the page that obeys
// `prefers-reduced-motion` obeys the answer: styles through web/vite.config.ts, scripts through web/src/lib/motion.ts.
extension AppDelegate: NSMenuItemValidation {
    var reduceMotionChoice: Bool? { UserDefaults.standard.object(forKey: "ReduceMotion") as? Bool }
    var reduceMotion: Bool { reduceMotionChoice ?? NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }

    var reduceMotionScript: String {
        guard let choice = reduceMotionChoice else { return "document.documentElement.removeAttribute('data-reduce-motion');" }
        return "document.documentElement.setAttribute('data-reduce-motion', '\(choice ? "on" : "off")');"
    }

    @objc func toggleReduceMotion(_ sender: Any?) {
        UserDefaults.standard.set(!reduceMotion, forKey: "ReduceMotion")
        syncTitlebar()
    }

    // The checkmark is read when the menu opens, so it follows macOS while the person has not chosen.
    func validateMenuItem(_ item: NSMenuItem) -> Bool {
        if item.action == #selector(toggleReduceMotion(_:)) { item.state = reduceMotion ? .on : .off }
        if item.action == #selector(zoomIn(_:)) { return webView != nil && webView.pageZoom < 2 }
        if item.action == #selector(zoomOut(_:)) { return webView != nil && webView.pageZoom > 0.5 }
        if item.action == #selector(actualSize(_:)) { return webView != nil }
        return true
    }
}

@main enum Main {
    static func main() {
        let args = CommandLine.arguments
        if let at = args.firstIndex(of: "--install-update") { Installer.run(Array(args[(at + 1)...])) }
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.run()
    }
}
