// The title bar's update corner: what an update is doing, in words, and an Update button while there is one.
// The button opens what got better, Restart and Skip This Version; ignored, the update installs at quit.
import Cocoa

@MainActor final class UpdateIndicator: NSObject {
    private enum Action { case update, tryAgain }

    private let updater: Updater
    private let accessory = NSTitlebarAccessoryViewController()
    private let holder = NSView()
    private let label = Words()
    private let button = IndicatorButton()
    private let popover = NSPopover()
    private var action: Action?
    private var inner: CGFloat = 288    // the card's text width
    var restart: () -> Void = {}
    var cancelRestart: () -> Void = {}

    init(window: NSWindow, updater: Updater) {
        self.updater = updater
        super.init()
        button.target = self
        button.action = #selector(press)
        holder.addSubview(label)
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
        guard let (text, action) = line() else {
            // A shown title bar accessory doesn't disappear by isHidden alone: its view hides too.
            accessory.isHidden = true
            holder.isHidden = true
            popover.performClose(nil)
            return
        }
        self.action = action
        label.text = text
        if case .answered(let notice) = updater.activity { label.toolTip = notice.detail } else { label.toolTip = nil }
        button.isHidden = action == nil
        button.attributedTitle = words(action == .tryAgain ? "Try Again" : "Update", weight: .medium, alignment: .center)
        let height = max(accessory.view.window.map { $0.frame.height - $0.contentLayoutRect.height } ?? 32, 28)
        let buttonWidth = action == nil ? 0 : ceil(button.attributedTitle.size().width) + 20
        let textWidth = min(ceil(text.size().width) + 4, 420 - buttonWidth)
        let textHeight = ceil(text.size().height)
        label.frame = NSRect(x: 0, y: ((height - textHeight) / 2).rounded(), width: textWidth, height: textHeight)
        button.frame = NSRect(x: textWidth + 8, y: ((height - 22) / 2).rounded(), width: buttonWidth, height: 22)
        holder.frame = NSRect(x: 0, y: 0, width: (action == nil ? textWidth : button.frame.maxX) + 8, height: height)
        holder.isHidden = false
        accessory.isHidden = false
        if popover.isShown {
            if action == .update { popover.contentViewController = card() } else { popover.performClose(nil) }
        }
    }

    /// Opens the card for a check asked for from the menu.
    func reveal() {
        refresh()
        guard action == .update, !popover.isShown else { return }
        popover.contentViewController = card()
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
    }

    @objc private func press() {
        if action == .tryAgain { return checkAgain() }
        if popover.isShown { return popover.performClose(nil) }
        reveal()
    }

    // MARK: the corner

    private func line() -> (NSAttributedString, Action?)? {
        let state = updater.state, version = state.version ?? ""
        switch updater.activity {
        case .checking: return (words("Checking for updates…", .secondaryLabelColor), nil)
        case .downloading(let share): return (words("Downloading Verticals \(version) · \(share)%", .secondaryLabelColor), nil)
        case .waitingForAgent: return (words("Restarts when the agent finishes"), .update)
        case .answered(let notice): return (words(notice.title), notice.detail.isEmpty ? nil : .tryAgain)
        case .none: break
        }
        if let failure = state.failure, updater.readyToInstall { return (words(failure.title), .update) }
        if let blocked = updater.blocked, state.skipped != state.version { return (words(blocked.title), .update) }
        if updater.readyToInstall && !state.summary.isEmpty { return (words(state.summary), .update) }
        return nil
    }

    private func words(_ text: String, _ color: NSColor = .labelColor, weight: NSFont.Weight = .regular,
                       alignment: NSTextAlignment = .natural) -> NSAttributedString {
        let style = NSMutableParagraphStyle()
        style.alignment = alignment
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
        if let blocked = updater.blocked, state.failure == nil || !updater.readyToInstall {
            add(text(blocked.detail, size: 13), after: 0)
            add(buttons([("OK", #selector(skip), true)]), after: 16)
        } else if let failure = state.failure, updater.activity != .waitingForAgent {
            add(text("Verticals \(version) didn't install", size: 15, weight: .semibold), after: 0)
            add(text(failure.detail, size: 13), after: 6)
            add(buttons([("Skip This Version", #selector(skip), false), ("Try Again", #selector(restartNow), true)]), after: 16)
        } else {
            // The words beside the button already say what got better; the card holds the details.
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

// A grey button, flat like the title bar around it: darker under the pointer and when pressed.
final class IndicatorButton: NSButton {
    private var inside = false { didSet { paint() } }
    private var pressed = false { didSet { paint() } }

    override init(frame: NSRect) {
        super.init(frame: frame)
        isBordered = false
        refusesFirstResponder = true
        wantsLayer = true
        layer?.cornerRadius = 6
        paint()
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
        layer?.backgroundColor = NSColor.black.withAlphaComponent(pressed ? 0.14 : inside ? 0.1 : 0.06).cgColor
    }
}

// Drawn rather than a text field: a text field in the title bar greys out with the window, the button beside it doesn't.
final class Words: NSView {
    var text = NSAttributedString() {
        didSet {
            needsDisplay = true
            setAccessibilityValue(text.string)
        }
    }

    override init(frame: NSRect) {
        super.init(frame: frame)
        setAccessibilityElement(true)
        setAccessibilityRole(.staticText)
    }

    required init?(coder: NSCoder) { fatalError() }

    override var mouseDownCanMoveWindow: Bool { true }

    override func draw(_ dirtyRect: NSRect) {
        text.draw(with: bounds, options: [.usesLineFragmentOrigin, .truncatesLastVisibleLine])
    }
}
