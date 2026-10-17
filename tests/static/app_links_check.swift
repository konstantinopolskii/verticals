// Run by tests/static/test_app_links.py: AppLinks.swift (desktop/macos) compiled with this file alone, no window, nothing launched.
// Prints what the app's task-link and connect-line builders make of fixed inputs, as one JSON object.
import Foundation

@main enum AppLinksCheck {
    static func main() {
        let ui = URL(string: "http://127.0.0.1:8288/")!
        func task(_ text: String) -> String { URL(string: text).flatMap { AppLinks.taskID($0) } ?? "-" }
        var out: [String: Any] = [:]
        out["accepted"] = ["verticals://goal/AB12cd34", "VERTICALS://GOAL/x_y-z", "verticals://goal/AB12cd34/", "verticals://goal/AB12cd34//"].map(task)
        out["refused"] = [
            "verticals://goal/", "verticals://goal", "verticals://goal/a/b", "verticals://goal/a%20b", "verticals://goal/a.b",
            "verticals://goal/a%2Fb", "verticals://goal/..", "verticals://goal//AB12cd34", "verticals://goal/" + String(repeating: "x", count: 101),
            "verticals://doc/AB12cd34", "verticals://AB12cd34", "http://goal/AB12cd34", "verticals:goal/AB12cd34",
        ].map(task)
        out["longest"] = task("verticals://goal/" + String(repeating: "x", count: 100)).count
        out["fragment"] = AppLinks.fragment(task: "AB12cd34")
        out["board"] = AppLinks.boardURL(task: "AB12cd34", ui: ui)?.absoluteString ?? "-"
        out["boardRefused"] = AppLinks.boardURL(task: "a/b", ui: ui)?.absoluteString ?? "-"
        out["boardOver"] = AppLinks.boardURL(task: "AB12cd34", ui: URL(string: "http://127.0.0.1:8288/h/2026-08-01#goal/old")!)?.absoluteString ?? "-"

        let headers = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "/state/mcp-headers.json"
        let claude = AppLinks.claudeAddArguments(mcpURL: "http://127.0.0.1:8281/mcp", headersFile: headers) ?? []
        out["claudeAdd"] = Array(claude.dropLast())
        out["claudeServer"] = claude.last.flatMap { $0.data(using: .utf8) }.flatMap { try? JSONSerialization.jsonObject(with: $0) } ?? [:]
        out["claudeRemove"] = AppLinks.claudeRemoveArguments
        out["codexAdd"] = AppLinks.codexAddArguments(
            python: "/Applications/Verticals.app/Contents/Resources/python/bin/python3",
            relay: "/Applications/Verticals.app/Contents/Resources/desktop/chat/mcp_proxy.py",
            mcpURL: "http://127.0.0.1:8281/mcp", headersFile: headers)
        out["codexRemove"] = AppLinks.codexRemoveArguments
        out["agentEnv"] = AppLinks.agentEnvironment("""
            # whose sign-in the agents use
            CLAUDE_CONFIG_DIR=~/.claude-personal
            export CODEX_HOME="/Users/sample/codex home"

            PATH=/tmp/evil
            ANTHROPIC_API_KEY=sk-not-read
            CLAUDE_CODE_OAUTH_TOKEN=/not/read/either
            """, home: "/Users/sample")
        out["agentEnvRelative"] = AppLinks.agentEnvironment("CLAUDE_CONFIG_DIR=claude-personal\nCODEX_HOME='~'", home: "/Users/sample")
        let data = try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys])
        print(String(data: data, encoding: .utf8)!)
    }
}
