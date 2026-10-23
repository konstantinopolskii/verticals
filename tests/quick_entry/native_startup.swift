import Cocoa
import WebKit
@main struct StartupCheck {
    static var probe: Probe!
    static func main() { let app=NSApplication.shared; probe=Probe(); app.delegate=probe; app.run() }
}
@MainActor final class Probe: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ note:Notification) {
        Task {
            let state=URL(fileURLWithPath:"/tmp/quick-entry-startup-"+UUID().uuidString)
            try! FileManager.default.createDirectory(at:state,withIntermediateDirectories:true)
            defer { try? FileManager.default.removeItem(at:state) }
            try! Data("{\"binding\":\"key:90\"}".utf8).write(to:state.appendingPathComponent("quick-entry-binding.json"))
            let server=Process()
            server.executableURL=URL(fileURLWithPath:"/usr/bin/python3")
            server.arguments=["-c", """
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def do_GET(self):
  self.send_response(302)
  self.send_header('Location','http://127.0.0.1:8388'+self.path)
  self.end_headers()
time.sleep(1.5)
HTTPServer(('127.0.0.1',8387),Handler).handle_request()
"""]
            try! server.run()
            defer { if server.isRunning { server.terminate() } }
            let entry=QuickEntry(state:state,base:URL(string:"http://127.0.0.1:8387/")!,web:WKWebView())
            assert(entry.entryWeb.url == nil,"Do not load the bubble during startup before the backend is ready")
            entry.show()
            for _ in 0..<100 {
                if (try? await entry.entryWeb.evaluateJavaScript("!!window.quickEntry")) as? Bool == true {
                    let label=try! await entry.entryWeb.evaluateJavaScript("document.querySelector('textarea').getAttribute('aria-label')") as! String
                    assert(label=="Quick Entry")
                    assert(entry.loaded && !entry.entryWeb.isHidden && entry.loadingLabel.isHidden)
                    let image=try! await entry.entryWeb.takeSnapshot(configuration:nil)
                    let rep=NSBitmapImageRep(data:image.tiffRepresentation!)!
                    try! rep.representation(using:.png,properties:[:])!.write(to:URL(fileURLWithPath:"/tmp/quick-entry-evidence/cold-start.png"))
                    print("Cold startup: failed early request recovered after delayed server start; input visible")
                    NSApp.terminate(nil);return
                }
                try? await Task.sleep(nanoseconds:100_000_000)
            }
            fatalError("First invocation did not load the bubble")
        }
    }
}
