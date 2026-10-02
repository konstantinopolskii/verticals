// Verticals.app: a native window (WKWebView) around the desktop launcher.
// On launch it starts Resources/desktop/launcher.py with the bundled Python (PostgreSQL, API, MCP,
// UI gateway) unless Verticals is already running, waits until it is healthy, and shows the UI.
// Quitting stops what it started. Resources mirrors the repository layout (see desktop/macos/bundle.py).
// Updates come from the repository's GitHub releases (see "updates" below).
import Cocoa
import WebKit

let uiURL = URL(string: "http://127.0.0.1:8288/")!
let healthURL = URL(string: "http://127.0.0.1:8288/healthz")!
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
        Task { await checkForUpdates(manual: false) }
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

    // MARK: updates

    // A newer GitHub release is offered at launch and from the menu. Its zip is unpacked next to the
    // app; once this process has quit (stopping the backend), a shell swaps the bundles and opens
    // the new one. Data in Application Support is not touched.

    struct Release: Decodable {
        struct Asset: Decodable { let name: String; let browserDownloadUrl: URL }
        let tagName: String
        let assets: [Asset]
    }

    struct UpdateError: LocalizedError {
        let errorDescription: String?
        init(_ message: String) { errorDescription = message }
    }

    var version: String { Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0" }
    var updating = false

    @objc func checkForUpdatesNow(_ sender: Any?) { Task { await checkForUpdates(manual: true) } }

    func checkForUpdates(manual: Bool) async {
        guard !updating else { return }
        let found: (version: String, zip: URL)?
        do {
            found = try await latestRelease()
        } catch {
            NSLog("Verticals update check: \(error.localizedDescription)")
            if manual { await tell("Could not check for updates", error.localizedDescription) }
            return
        }
        guard let found, found.version.compare(version, options: .numeric) == .orderedDescending else {
            if manual { await tell("Verticals \(version) is up to date") }
            return
        }
        let offer = NSAlert()
        offer.messageText = "Verticals \(found.version) is available"
        offer.informativeText = "You have \(version). Verticals downloads it, keeps a copy of the database, restarts and opens the same board."
        offer.addButton(withTitle: "Update")
        offer.addButton(withTitle: "Later")
        guard await offer.beginSheetModal(for: window) == .alertFirstButtonReturn else { return }
        updating = true
        window.titleVisibility = .visible
        window.subtitle = "Downloading Verticals \(found.version)…"
        do {
            try await install(found.version, from: found.zip)
        } catch {
            updating = false
            window.subtitle = ""
            window.titleVisibility = .hidden
            await tell("Could not update Verticals", error.localizedDescription)
        }
    }

    func latestRelease() async throws -> (version: String, zip: URL)? {
        var request = URLRequest(url: releasesAPI)
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        let (data, response) = try await URLSession.shared.data(for: request)
        switch (response as? HTTPURLResponse)?.statusCode ?? 0 {
        case 200:
            break
        case 404:
            // GitHub answers 404 both when nothing is released yet and when the repository is not public.
            let repo = releasesAPI.deletingLastPathComponent().deletingLastPathComponent()
            let (_, answer) = try await URLSession.shared.data(from: repo)
            guard (answer as? HTTPURLResponse)?.statusCode == 200 else {
                throw UpdateError("\(repo.path) is not public on GitHub.")
            }
            return nil
        case let code:
            throw UpdateError("GitHub answered \(code).")
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let release = try decoder.decode(Release.self, from: data)
        guard let zip = release.assets.first(where: { $0.name == "Verticals.zip" }) else {
            throw UpdateError("Release \(release.tagName) has no Verticals.zip.")
        }
        let tag = release.tagName
        return (tag.hasPrefix("v") ? String(tag.dropFirst()) : tag, zip.browserDownloadUrl)
    }

    func install(_ latest: String, from zip: URL) async throws {
        let app = Bundle.main.bundleURL
        let folder = app.deletingLastPathComponent()
        guard FileManager.default.isWritableFile(atPath: folder.path) else {
            throw UpdateError("Verticals cannot replace itself in \(folder.path). Move it to Applications first.")
        }
        // On the app's volume, so the swap is a rename.
        let stage = try FileManager.default.url(for: .itemReplacementDirectory, in: .userDomainMask,
                                                appropriateFor: app, create: true)
        do {
            let (file, response) = try await URLSession.shared.download(from: zip)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else {
                throw UpdateError("The download failed.")
            }
            let archive = stage.appendingPathComponent("Verticals.zip")
            try FileManager.default.moveItem(at: file, to: archive)
            let fresh = stage.appendingPathComponent("Verticals.app")
            guard await run("/usr/bin/ditto", "-x", "-k", archive.path, stage.path) == 0,
                  let info = NSDictionary(contentsOf: fresh.appendingPathComponent("Contents/Info.plist")),
                  info["CFBundleIdentifier"] as? String == Bundle.main.bundleIdentifier,
                  info["CFBundleShortVersionString"] as? String == latest else {
                throw UpdateError("The download is not Verticals \(latest).")
            }
            _ = await run("/usr/bin/xattr", "-dr", "com.apple.quarantine", fresh.path)
            guard await run("/usr/bin/codesign", "--verify", "--deep", "--strict", fresh.path) == 0 else {
                throw UpdateError("The downloaded app is damaged: its signature does not verify.")
            }
            // Swaps only under a stopped database, after a copy of it lands in backups/ (last three
            // kept); otherwise the old app opens again. Steps go to update.log in the state folder.
            let swap = Process()
            swap.executableURL = URL(fileURLWithPath: "/bin/sh")
            swap.arguments = ["-c", """
                app=$2 stage=$3 state=$4 from=$5 to=$6 pidfile=$4/postgres/postmaster.pid
                say() { mkdir -p "$state" && echo "$(date '+%F %T') $from -> $to: $1" >> "$state/update.log"; }
                cancel() { say "$1"; rm -rf "$stage"; open "$app"; exit 1; }
                while kill -0 "$1" 2>/dev/null; do sleep 0.2; done
                i=0
                while [ -e "$pidfile" ] && kill -0 "$(head -1 "$pidfile")" 2>/dev/null; do
                  i=$((i + 1)); [ $i -gt 300 ] && cancel "cancelled, PostgreSQL is still running"; sleep 0.2
                done
                if [ -d "$state/postgres" ]; then
                  copy="$state/backups/$(date +%Y%m%d-%H%M%S)-$from"
                  mkdir -p "$state/backups" && ditto "$state/postgres" "$copy" || cancel "cancelled, no database copy"
                  ls -r "$state/backups" | tail -n +4 | while read -r old; do rm -rf "$state/backups/$old"; done
                  say "database copied to $copy"
                fi
                mv "$app" "$stage/previous.app" || cancel "cancelled, could not move the old app aside"
                if ! mv "$stage/Verticals.app" "$app"; then
                  mv "$stage/previous.app" "$app"; cancel "cancelled, could not move the new app in"
                fi
                rm -rf "$stage"
                say "updated"
                open "$app"
                """, "swap", String(ProcessInfo.processInfo.processIdentifier), app.path, stage.path,
                stateDir.path, version, latest]
            try swap.run()
        } catch {
            try? FileManager.default.removeItem(at: stage)
            throw error
        }
        // From the run loop, not this main-queue task: termination waits for a main-queue reply.
        NSApp.perform(#selector(NSApplication.terminate(_:)), with: nil, afterDelay: 0)
    }

    func run(_ tool: String, _ args: String...) async -> Int32 {
        await withCheckedContinuation { done in
            let process = Process()
            process.executableURL = URL(fileURLWithPath: tool)
            process.arguments = args
            process.terminationHandler = { done.resume(returning: $0.terminationStatus) }
            do { try process.run() } catch { done.resume(returning: -1) }
        }
    }

    func tell(_ title: String, _ detail: String = "") async {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = detail
        _ = await alert.beginSheetModal(for: window)
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

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
