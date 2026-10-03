// Updates from the repository's GitHub releases (desktop/README.md, "Releases and updates"). A newer
// release downloads in the background into <state>/updates and installs when Verticals quits, or at
// once from Restart in the title bar. Only a check asked for from the menu answers out loud.
import Cocoa
import CryptoKit

struct Notice: Codable, Equatable {
    var title: String   // the title bar's line
    var detail: String  // what happened and what to do, in the popover
}

// A file of a release: the whole app, or the lite one without the runtime (bundle.py, RUNTIME_DIRS).
struct Download: Codable, Equatable {
    var url: URL
    var size: Int64
    var sha256: String?
}

// Kept in <state>/updates/state.json, so a quit, a crash or a restart loses nothing.
struct UpdateState: Codable {
    var version: String?
    var summary = ""
    var notes: [String] = []
    var full: Download?
    var lite: Download?
    var runtime: String?    // the release's Resources/RUNTIME: the lite zip fits an app with the same one
    var ready = false       // unpacked and verified in updates/<version>/Verticals.app
    var restart = false     // Restart was pressed: a crash before the swap installs at the next launch
    var skipped: String?
    var failure: Notice?
    var minimum: String?    // the macOS the release needs

    static func file(_ stateDir: URL) -> URL { stateDir.appendingPathComponent("updates/state.json") }

    static func load(_ stateDir: URL) -> UpdateState {
        (try? Data(contentsOf: file(stateDir))).flatMap { try? JSONDecoder().decode(UpdateState.self, from: $0) }
            ?? UpdateState()
    }

    func save(_ stateDir: URL) {
        let url = UpdateState.file(stateDir)
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? JSONEncoder().encode(self).write(to: url, options: .atomic)
    }
}

struct UpdateError: LocalizedError {
    let errorDescription: String?
    init(_ message: String) { errorDescription = message }
}

@MainActor final class Updater {
    enum Activity: Equatable { case none, checking, downloading(Int), waitingForAgent, answered(Notice) }

    let stateDir: URL
    let current = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0"
    private(set) var state: UpdateState
    var activity = Activity.none { didSet { if activity != oldValue { changed() } } }
    var changed: () -> Void = {}
    var reveal: () -> Void = {}

    private var running = false
    private var asked = false       // a menu check is waiting for the answer
    private var fetching = false
    private var retry: TimeInterval = 15 * 60
    private var timer: Timer?

    init(stateDir: URL) {
        self.stateDir = stateDir
        state = UpdateState.load(stateDir)
    }

    var folder: URL { stateDir.appendingPathComponent("updates") }
    var staged: URL? { state.version.map { folder.appendingPathComponent("\($0)/Verticals.app") } }
    var readyToInstall: Bool {
        state.ready && state.version != state.skipped && staged.map { FileManager.default.fileExists(atPath: $0.path) } == true
    }
    /// Why this Mac can't take the release: an older macOS, or an app folder Verticals can't write to.
    var blocked: Notice? {
        guard let version = state.version else { return nil }
        if let minimum = state.minimum {
            let parts = minimum.split(separator: ".").compactMap { Int($0) }
            let needed = OperatingSystemVersion(majorVersion: parts.first ?? 0, minorVersion: parts.dropFirst().first ?? 0, patchVersion: 0)
            if !ProcessInfo.processInfo.isOperatingSystemAtLeast(needed) {
                let system = ProcessInfo.processInfo.operatingSystemVersion.majorVersion
                let named = parts.count > 1 && parts[1] > 0 ? "\(parts[0]).\(parts[1])" : "\(parts.first ?? 0)"
                return Notice(title: "Verticals \(version) needs macOS \(named)",
                              detail: "Verticals \(current) is the last version for macOS \(system); newer ones need macOS \(named).")
            }
        }
        if !FileManager.default.isWritableFile(atPath: Bundle.main.bundleURL.deletingLastPathComponent().path) {
            return Notice(title: "Move Verticals to Applications to update",
                          detail: "Verticals can't replace itself where it is now. Move it to Applications and open it from there.")
        }
        return nil
    }

    func update(_ change: (inout UpdateState) -> Void) {
        change(&state)
        state.save(stateDir)
        changed()
    }

    // MARK: launch and schedule

    /// Forgets an update that is now installed. True when a Restart pressed before a crash still waits.
    func launch() -> Bool {
        if let version = state.version, version.compare(current, options: .numeric) != .orderedDescending {
            try? FileManager.default.removeItem(at: folder.appendingPathComponent(version))
            update { $0 = UpdateState(skipped: $0.skipped) }
        } else if state.ready && !readyToInstall && state.version != state.skipped {
            update { $0.ready = false }
        }
        return state.restart && readyToInstall
    }

    /// An install from the last quit still runs: it opens Verticals itself when it is done.
    static func installing(_ stateDir: URL) -> Bool {
        let lock = stateDir.appendingPathComponent("updates/installing")
        guard let pid = (try? String(contentsOf: lock, encoding: .utf8)).flatMap({ Int32($0) }), kill(pid, 0) == 0 else {
            return false
        }
        FileManager.default.createFile(atPath: stateDir.appendingPathComponent("updates/open-after").path, contents: nil)
        return true
    }

    func start() {
        Task { await check(manual: false) }
        timer = Timer.scheduledTimer(withTimeInterval: 6 * 3600, repeats: true) { [weak self] _ in
            Task { await self?.check(manual: false) }
        }
        timer?.tolerance = 600
    }

    // A failed background check stays invisible and comes back later: 15 min, 30, 1 h, … up to 6 h.
    private func later() {
        let delay = retry
        retry = min(retry * 2, 6 * 3600)
        Task {
            try? await Task.sleep(nanoseconds: UInt64(delay * 1e9))
            await check(manual: false)
        }
    }

    // MARK: check and download

    func check(manual: Bool) async {
        if manual { asked = true }
        guard !running else {
            if manual, activity == .none { activity = .checking }
            return
        }
        running = true
        if asked && activity != .waitingForAgent { activity = .checking }
        defer {
            running = false
            asked = false
            switch activity {
            case .checking, .downloading: activity = .none
            default: break
            }
        }
        do {
            guard let release = try await latestRelease(),
                  release.version.compare(current, options: .numeric) == .orderedDescending else {
                retry = 15 * 60
                reply(Notice(title: "Verticals \(current) is the latest version", detail: ""))
                return
            }
            if release.version != state.version {
                try await adopt(release)
            }
            if asked && state.skipped == state.version { update { $0.skipped = nil } }
            guard state.skipped != state.version, blocked == nil else {
                if blocked != nil { reply() }
                return
            }
            if !state.ready { try await download() }
            retry = 15 * 60
            reply(state.summary.isEmpty ? Notice(title: "Verticals \(release.version) installs when you quit", detail: "") : nil)
        } catch {
            NSLog("Verticals update: \(error.localizedDescription)")
            if asked { reply(Notice(title: "Couldn't check for updates", detail: error.localizedDescription)) } else { later() }
        }
    }

    // The menu's check answers where its progress was, never in a window: words, or with none the
    // card. Plain words leave after 10 s; an error, with Try Again beside it, after 30 s.
    private func reply(_ notice: Notice? = nil) {
        guard asked, activity != .waitingForAgent else { return }
        guard let notice else {
            activity = .none
            return reveal()
        }
        activity = .answered(notice)
        Task {
            try? await Task.sleep(nanoseconds: notice.detail.isEmpty ? 10_000_000_000 : 30_000_000_000)
            if activity == .answered(notice) { activity = .none }
        }
    }

    struct Release {
        let version: String
        let summary: String
        let notes: [String]
        let full: Download
        let lite: Download?
        let info: URL?
    }

    // The release's text on GitHub: a line above the list is the summary beside the Update button, the list is
    // the card's notes. Comments, headings and the rest are for people reading the release page.
    static func words(_ body: String) -> (summary: String, notes: [String]) {
        let text = body.replacingOccurrences(of: "<!--[\\s\\S]*?-->", with: "", options: .regularExpression)
        var summary = "", notes: [String] = []
        for line in text.split(whereSeparator: \.isNewline).map({ $0.trimmingCharacters(in: .whitespaces) }) where !line.isEmpty {
            if line.hasPrefix("- ") || line.hasPrefix("* ") {
                notes.append(line.dropFirst(2).trimmingCharacters(in: .whitespaces))
            } else if notes.isEmpty, summary.isEmpty, !line.hasPrefix("#") {
                summary = line
            }
        }
        return (summary, notes)
    }

    func latestRelease() async throws -> Release? {
        struct Wire: Decodable {
            struct Asset: Decodable { let name: String; let browserDownloadUrl: URL; let size: Int64; let digest: String? }
            let tagName: String
            let body: String?
            let assets: [Asset]
        }
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
        let wire = try decoder.decode(Wire.self, from: data)
        func download(_ name: String) -> Download? {
            wire.assets.first { $0.name == name }.map { asset in
                Download(url: asset.browserDownloadUrl, size: asset.size,
                         sha256: asset.digest.flatMap { $0.hasPrefix("sha256:") ? String($0.dropFirst(7)) : nil })
            }
        }
        guard let full = download("Verticals.zip") else {
            throw UpdateError("Release \(wire.tagName) has no Verticals.zip.")
        }
        let version = wire.tagName.hasPrefix("v") ? String(wire.tagName.dropFirst()) : wire.tagName
        let words = Self.words(wire.body ?? "")
        return Release(version: version, summary: words.summary, notes: words.notes, full: full,
                       lite: download("Verticals-lite.zip"), info: wire.assets.first { $0.name == "release.json" }?.browserDownloadUrl)
    }

    // A newer release replaces whatever was downloaded before; release.json says what it needs and holds.
    private func adopt(_ release: Release) async throws {
        struct Info: Decodable { let minMacos: String?; let runtime: String? }
        var info: Info?
        if let url = release.info {
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            info = try decoder.decode(Info.self, from: try await URLSession.shared.data(from: url).0)
        }
        discardDownload()
        update {
            $0 = UpdateState(version: release.version, summary: release.summary, notes: release.notes,
                             full: release.full, lite: release.lite, runtime: info?.runtime, skipped: $0.skipped,
                             minimum: info?.minMacos)
        }
    }

    // The lite zip when this app already holds the release's runtime; the whole app otherwise, and when
    // the lite one doesn't come together.
    private func download() async throws {
        guard let version = state.version, let full = state.full else { return }
        if let lite = state.lite, let runtime = state.runtime, runtime == installedRuntime {
            do {
                return try await stage(version, from: lite, completing: true)
            } catch {
                NSLog("Verticals update: the lite download didn't come together, taking the whole app: \(error.localizedDescription)")
            }
        }
        try await stage(version, from: full, completing: false)
    }

    // Must match bundle.py's RUNTIME_DIRS.
    private static let runtimeDirs = ["pg", "python", "site"]

    private var installedRuntime: String? {
        Bundle.main.url(forResource: "RUNTIME", withExtension: nil)
            .flatMap { try? String(contentsOf: $0, encoding: .utf8) }?
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func stage(_ version: String, from source: Download, completing: Bool) async throws {
        let part = folder.appendingPathComponent("\(version)-\(source.url.lastPathComponent).part")
        if !FileManager.default.fileExists(atPath: part.path) {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            FileManager.default.createFile(atPath: part.path, contents: nil)
        }
        let have = (try? FileManager.default.attributesOfItem(atPath: part.path)[.size] as? Int64) ?? 0
        if have < source.size || source.size == 0 {
            fetching = true
            defer { fetching = false }
            try await Fetch(url: source.url, to: part, from: have, total: source.size) { [weak self] share in
                Task { @MainActor in
                    guard let self, self.asked, self.fetching else { return }
                    self.activity = .downloading(Int(share * 100))
                }
            }.run()
        }
        let unpacked = folder.appendingPathComponent(version)
        func discard(_ reason: String) -> UpdateError {
            try? FileManager.default.removeItem(at: unpacked)
            try? FileManager.default.removeItem(at: part)
            return UpdateError(reason)
        }
        if let expected = source.sha256, try sha256(of: part) != expected {
            throw discard("The download of Verticals \(version) is damaged.")
        }
        try? FileManager.default.removeItem(at: unpacked)
        try FileManager.default.createDirectory(at: unpacked, withIntermediateDirectories: true)
        let app = unpacked.appendingPathComponent("Verticals.app")
        guard await run("/usr/bin/ditto", "-x", "-k", part.path, unpacked.path) == 0,
              let info = NSDictionary(contentsOf: app.appendingPathComponent("Contents/Info.plist")),
              info["CFBundleIdentifier"] as? String == Bundle.main.bundleIdentifier,
              info["CFBundleShortVersionString"] as? String == version else {
            throw discard("The download is not Verticals \(version).")
        }
        if completing, let own = Bundle.main.resourceURL {
            // The runtime comes from this app; on APFS it is a clone, so it takes no time and no space.
            for dir in Self.runtimeDirs {
                let from = own.appendingPathComponent(dir).path
                let into = app.appendingPathComponent("Contents/Resources/\(dir)").path
                if clonefile(from, into, 0) != 0 { try FileManager.default.copyItem(atPath: from, toPath: into) }
            }
        }
        _ = await run("/usr/bin/xattr", "-dr", "com.apple.quarantine", app.path)
        // The signature seals the whole app as it was built, the runtime included, so this also proves
        // that a completed lite app is byte for byte the release.
        guard await run("/usr/bin/codesign", "--verify", "--deep", "--strict", app.path) == 0 else {
            throw discard("The downloaded app is damaged: its signature does not verify.")
        }
        try? FileManager.default.removeItem(at: part)
        update { $0.ready = true }
    }

    private func discardDownload() {
        for item in (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? []
        where item.lastPathComponent != "state.json" {
            try? FileManager.default.removeItem(at: item)
        }
    }

    private func sha256(of file: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        var hash = SHA256()
        while let chunk = try handle.read(upToCount: 1 << 20), !chunk.isEmpty { hash.update(data: chunk) }
        return hash.finalize().map { String(format: "%02x", $0) }.joined()
    }

    // MARK: the person's choices

    func skip() {
        discardDownload()
        update { $0 = UpdateState(skipped: $0.version) }
    }

    /// Hands the staged app to an installer that swaps it in once this process and its database stop.
    func installOnQuit(relaunch: Bool) {
        guard readyToInstall, let executable = Bundle.main.executableURL else { return }
        let installer = Process()
        installer.executableURL = executable
        installer.arguments = ["--install-update", String(getpid()), Bundle.main.bundleURL.path, stateDir.path,
                               relaunch ? "relaunch" : "stay"]
        try? installer.run()
    }
}

// Writes a download to a file from `offset` on, asking the server for the rest with Range.
final class Fetch: NSObject, URLSessionDataDelegate {
    let url: URL, file: URL, total: Int64, progress: (Double) -> Void
    private var offset: Int64
    private var handle: FileHandle?
    private var done: CheckedContinuation<Void, Error>?
    private var failure: Error?

    init(url: URL, to file: URL, from offset: Int64, total: Int64, progress: @escaping (Double) -> Void) {
        self.url = url
        self.file = file
        self.offset = offset
        self.total = total
        self.progress = progress
    }

    func run() async throws {
        handle = try FileHandle(forWritingTo: file)
        try handle?.seek(toOffset: UInt64(offset))
        defer { try? handle?.close() }
        var request = URLRequest(url: url, timeoutInterval: 60)
        if offset > 0 { request.setValue("bytes=\(offset)-", forHTTPHeaderField: "Range") }
        let session = URLSession(configuration: .ephemeral, delegate: self, delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            done = continuation
            session.dataTask(with: request).resume()
        }
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        switch (response as? HTTPURLResponse)?.statusCode {
        case 206:
            completionHandler(.allow)
        case 200:
            // The server sent the whole file: start over.
            offset = 0
            try? handle?.truncate(atOffset: 0)
            completionHandler(.allow)
        case let code:
            failure = UpdateError("The download failed (\(code ?? 0)).")
            completionHandler(.cancel)
        }
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        handle?.write(data)
        offset += Int64(data.count)
        if total > 0 { progress(Double(offset) / Double(total)) }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error = failure ?? error { done?.resume(throwing: error) } else { done?.resume() }
        done = nil
    }
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

// `Verticals --install-update <pid> <app> <state> relaunch|stay`, started by a quitting Verticals.
// Waits for that process and its PostgreSQL to stop, copies the database to backups/ (the last three
// stay), swaps the staged app in with one atomic rename and opens it when asked. A failure keeps the
// old app, is written to update.log and is shown in the title bar at the next launch.
enum Installer {
    static func run(_ args: [String]) -> Never {
        guard args.count == 4, let pid = Int32(args[0]) else { exit(2) }
        let app = URL(fileURLWithPath: args[1]), stateDir = URL(fileURLWithPath: args[2])
        let relaunch = args[3] == "relaunch"
        let files = FileManager.default
        let folder = stateDir.appendingPathComponent("updates")
        let lock = folder.appendingPathComponent("installing"), openAfter = folder.appendingPathComponent("open-after")
        var state = UpdateState.load(stateDir)
        guard let to = state.version, state.ready else { exit(0) }
        let from = Bundle(url: app)?.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?"
        try? String(getpid()).write(to: lock, atomically: true, encoding: .utf8)

        func stamp(_ format: String) -> String {
            let formatter = DateFormatter()
            formatter.dateFormat = format
            return formatter.string(from: Date())
        }
        func say(_ line: String) {
            let entry = Data("\(stamp("yyyy-MM-dd HH:mm:ss")) \(from) -> \(to): \(line)\n".utf8)
            let log = stateDir.appendingPathComponent("update.log")
            if let handle = try? FileHandle(forWritingTo: log) {
                handle.seekToEndOfFile()
                handle.write(entry)
                try? handle.close()
            } else {
                try? entry.write(to: log)
            }
        }
        func finish(_ failure: Notice?) -> Never {
            state.restart = false
            if let failure {
                state.failure = failure
                say("not installed: \(failure.detail)")
            } else {
                state.ready = false
                say("updated")
            }
            state.save(stateDir)
            try? files.removeItem(at: lock)
            if relaunch || files.fileExists(atPath: openAfter.path) {
                try? files.removeItem(at: openAfter)
                let open = Process()
                open.executableURL = URL(fileURLWithPath: "/usr/bin/open")
                open.arguments = [app.path]
                try? open.run()
                open.waitUntilExit()
            }
            exit(failure == nil ? 0 : 1)
        }
        func tool(_ path: String, _ args: String...) -> Bool {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: path)
            process.arguments = args
            guard (try? process.run()) != nil else { return false }
            process.waitUntilExit()
            return process.terminationStatus == 0
        }

        while kill(pid, 0) == 0 { usleep(200_000) }
        let postmaster = stateDir.appendingPathComponent("postgres/postmaster.pid")
        for waited in 0... {
            guard let line = (try? String(contentsOf: postmaster, encoding: .utf8))?.split(separator: "\n").first,
                  let pg = Int32(line), kill(pg, 0) == 0 else { break }
            if waited == 300 {
                finish(Notice(title: "The update didn't install",
                              detail: "Its database was still running when Verticals quit. It tries again the next time you quit."))
            }
            usleep(200_000)
        }
        let database = stateDir.appendingPathComponent("postgres")
        if files.fileExists(atPath: database.path) {
            let backups = stateDir.appendingPathComponent("backups")
            let copy = backups.appendingPathComponent("\(stamp("yyyyMMdd-HHmmss"))-\(from)")
            try? files.createDirectory(at: backups, withIntermediateDirectories: true)
            guard tool("/usr/bin/ditto", database.path, copy.path) else {
                try? files.removeItem(at: copy)
                finish(Notice(title: "The update didn't install",
                              detail: "Verticals couldn't copy its database before replacing itself. Check that the disk has free space; it tries again the next time you quit."))
            }
            let old = ((try? files.contentsOfDirectory(atPath: backups.path)) ?? []).sorted().dropLast(3)
            for name in old { try? files.removeItem(at: backups.appendingPathComponent(name)) }
            say("database copied to \(copy.path)")
        }
        // One atomic rename puts the update in place and the old app where the update was.
        let staged = folder.appendingPathComponent("\(to)/Verticals.app")
        var swapped = renamex_np(staged.path, app.path, UInt32(RENAME_SWAP)) == 0
        if !swapped && errno == EXDEV,
           let near = try? files.url(for: .itemReplacementDirectory, in: .userDomainMask, appropriateFor: app, create: true) {
            // The app lives on another volume: copy the update next to it first.
            let copy = near.appendingPathComponent("Verticals.app")
            swapped = tool("/usr/bin/ditto", staged.path, copy.path) && renamex_np(copy.path, app.path, UInt32(RENAME_SWAP)) == 0
            try? files.removeItem(at: near)
        }
        if swapped {
            try? files.removeItem(at: folder.appendingPathComponent(to))
            finish(nil)
        }
        finish(Notice(title: "The update didn't install",
                      detail: "Verticals couldn't replace itself in \(app.deletingLastPathComponent().path). Move it to Applications, then quit it to install the update."))
    }
}
