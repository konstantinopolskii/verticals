// The title bar's update line: one quiet line in a fixed place, only while there is something to say.
// A click opens what got better, Restart and Skip This Version; ignored, the update installs at quit.
import Cocoa

@MainActor final class UpdateIndicator: NSObject {
    private let updater: Updater
    private let accessory = NSTitlebarAccessoryViewController()
    private let holder = NSView()
    private let button = IndicatorButton()
    private let popover = NSPopover()
    private var inner: CGFloat = 288    // the card's text width
    var restart: () -> Void = {}
    var cancelRestart: () -> Void = {}

    init(window: NSWindow, updater: Updater) {
        self.updater = updater
        super.init()
        button.target = self
        button.action = #selector(toggle)
        holder.addSubview(button)
        accessory.view = holder
        accessory.layoutAttribute = .trailing
        accessory.isHidden = true
        window.addTitlebarAccessoryViewController(accessory)
        popover.behavior = .transient
        popover.appearance = NSAppearance(named: .aqua)
        refresh()
    }

    func refresh() {
        guard let (title, active) = line() else {
            // A shown title bar accessory doesn't disappear by isHidden alone: its view hides too.
            accessory.isHidden = true
            holder.isHidden = true
            popover.performClose(nil)
            return
        }
        button.opens = active
        button.attributedTitle = title
        button.setAccessibilityLabel(title.string)
        let height = max(accessory.view.window.map { $0.frame.height - $0.contentLayoutRect.height } ?? 32, 28)
        let width = min(ceil(title.size().width) + 16, 420)
        button.frame = NSRect(x: 0, y: ((height - 22) / 2).rounded(), width: width, height: 22)
        holder.frame = NSRect(x: 0, y: 0, width: width + 8, height: height)
        holder.isHidden = false
        accessory.isHidden = false
        if popover.isShown {
            if active { popover.contentViewController = card() } else { popover.performClose(nil) }
        }
    }

    /// Opens the card for a check asked for from the menu.
    func reveal() {
        refresh()
        guard button.opens, !popover.isShown, let window = button.window else { return }
        let card = card()
        popover.contentViewController = card
        // The arrow points into the line, as far right as keeps the whole card inside the window.
        let line = button.convert(button.bounds, to: nil)
        let fit = min(line.midX, window.frame.width - card.view.fittingSize.width / 2 - 25)
        let x = min(max(fit, line.minX + 10), line.maxX - 10)
        popover.show(relativeTo: NSRect(x: x - line.minX - 1, y: 0, width: 2, height: button.bounds.height),
                     of: button, preferredEdge: .minY)
    }

    @objc private func toggle() {
        if popover.isShown { return popover.performClose(nil) }
        reveal()
    }

    // MARK: the line

    private func line() -> (NSAttributedString, Bool)? {
        let state = updater.state, version = state.version ?? ""
        switch updater.activity {
        case .checking: return (words("Checking for updates…", .secondaryLabelColor), false)
        case .downloading(let share): return (words("Downloading Verticals \(version) · \(share)%", .secondaryLabelColor), false)
        case .waitingForAgent: return (words("Restarts when the agent finishes"), true)
        case .answered(let notice): return (words(notice.title), !notice.detail.isEmpty)
        case .none: break
        }
        if let failure = state.failure, updater.readyToInstall { return (words(failure.title), true) }
        if let blocked = updater.blocked, state.skipped != state.version { return (words(blocked.title), true) }
        if updater.readyToInstall && !state.summary.isEmpty {
            let title = NSMutableAttributedString(attributedString: words("Update", weight: .semibold))
            title.append(words(" · ", .secondaryLabelColor))
            title.append(words(state.summary))
            return (title, true)
        }
        return nil
    }

    private func words(_ text: String, _ color: NSColor = .labelColor, weight: NSFont.Weight = .regular) -> NSAttributedString {
        let style = NSMutableParagraphStyle()
        style.lineBreakMode = .byTruncatingTail
        return NSAttributedString(string: text, attributes: [.font: NSFont.systemFont(ofSize: 12, weight: weight),
                                                             .foregroundColor: color, .paragraphStyle: style])
    }

    // MARK: the card

    private func card() -> NSViewController {
        let state = updater.state, version = state.version ?? ""
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 0
        stack.edgeInsets = NSEdgeInsets(top: 16, left: 16, bottom: 16, right: 16)
        func add(_ view: NSView, after gap: CGFloat) {
            if let last = stack.arrangedSubviews.last { stack.setCustomSpacing(gap, after: last) }
            stack.addArrangedSubview(view)
        }
        // A one-sentence notice reads at 280; a list of changes at 320.
        inner = 248
        if case .answered(let notice) = updater.activity {
            add(text(notice.detail, size: 13), after: 0)
            add(buttons([("Try Again", #selector(checkAgain), true)]), after: 16)
        } else if let blocked = updater.blocked, state.failure == nil || !updater.readyToInstall {
            add(text(blocked.detail, size: 13), after: 0)
            add(buttons([("OK", #selector(skip), true)]), after: 16)
        } else if let failure = state.failure, updater.activity != .waitingForAgent {
            add(text("Verticals \(version) didn't install", size: 15, weight: .semibold), after: 0)
            add(text(failure.detail, size: 13), after: 6)
            add(buttons([("Skip This Version", #selector(skip), false), ("Try Again", #selector(restartNow), true)]), after: 16)
        } else {
            // The line above the card already says what got better; the card holds the details.
            inner = 288
            if !state.notes.isEmpty { add(bullets(state.notes), after: 0) }
            if updater.activity == .waitingForAgent {
                add(buttons([("Cancel Restart", #selector(cancel), false)]), after: 16)
            } else {
                add(text("Version \(version) installs the next time you quit.", size: 12, color: .secondaryLabelColor), after: 16)
                add(buttons([("Skip This Version", #selector(skip), false), ("Restart", #selector(restartNow), true)]), after: 10)
            }
        }
        stack.widthAnchor.constraint(equalToConstant: inner + 32).isActive = true
        let controller = NSViewController()
        controller.view = stack
        return controller
    }

    private func text(_ string: String, size: CGFloat, weight: NSFont.Weight = .regular, color: NSColor = .labelColor) -> NSTextField {
        let field = NSTextField(wrappingLabelWithString: string)
        field.font = .systemFont(ofSize: size, weight: weight)
        field.textColor = color
        field.isSelectable = false
        field.preferredMaxLayoutWidth = inner
        return field
    }

    private func bullets(_ notes: [String]) -> NSTextField {
        let style = NSMutableParagraphStyle()
        style.tabStops = [NSTextTab(textAlignment: .left, location: 12)]
        style.headIndent = 12
        style.paragraphSpacing = 4
        let list = NSAttributedString(string: notes.map { "•\t\($0)" }.joined(separator: "\n"),
                                      attributes: [.font: NSFont.systemFont(ofSize: 13), .foregroundColor: NSColor.labelColor,
                                                   .paragraphStyle: style])
        let field = NSTextField(labelWithAttributedString: list)
        field.isSelectable = false
        field.preferredMaxLayoutWidth = inner
        field.maximumNumberOfLines = 0
        field.lineBreakMode = .byWordWrapping
        return field
    }

    // The main action sits on the right, the way macOS orders a pair.
    private func buttons(_ items: [(String, Selector, Bool)]) -> NSView {
        let row = NSStackView()
        row.orientation = .horizontal
        row.spacing = 8
        row.addArrangedSubview(NSView())
        for (title, action, main) in items {
            let button = NSButton(title: title, target: self, action: action)
            button.bezelStyle = .rounded
            button.controlSize = .regular
            if main {
                button.keyEquivalent = "\r"
                button.bezelColor = .black
            }
            row.addArrangedSubview(button)
        }
        row.widthAnchor.constraint(equalToConstant: inner).isActive = true
        return row
    }

    @objc private func restartNow() {
        popover.performClose(nil)
        restart()
    }

    @objc private func checkAgain() {
        popover.performClose(nil)
        Task { await updater.check(manual: true) }
    }

    @objc private func skip() {
        popover.performClose(nil)
        updater.skip()
    }

    @objc private func cancel() {
        popover.performClose(nil)
        cancelRestart()
    }
}

// Flat like the title bar around it; a light fill under the pointer shows that it opens something.
final class IndicatorButton: NSButton {
    var opens = false { didSet { paint() } }
    private var inside = false { didSet { paint() } }
    private var pressed = false { didSet { paint() } }

    override init(frame: NSRect) {
        super.init(frame: frame)
        isBordered = false
        refusesFirstResponder = true
        wantsLayer = true
        layer?.cornerRadius = 6
    }

    required init?(coder: NSCoder) { fatalError() }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(NSTrackingArea(rect: .zero, options: [.mouseEnteredAndExited, .activeAlways, .inVisibleRect],
                                       owner: self))
    }

    override func mouseEntered(with event: NSEvent) { inside = true }
    override func mouseExited(with event: NSEvent) { inside = false }

    override func mouseDown(with event: NSEvent) {
        pressed = true
        super.mouseDown(with: event)
        pressed = false
    }

    private func paint() {
        let alpha = !opens ? 0 : pressed ? 0.1 : inside ? 0.06 : 0
        layer?.backgroundColor = NSColor.black.withAlphaComponent(alpha).cgColor
    }
}
