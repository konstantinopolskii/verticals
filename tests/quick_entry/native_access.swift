import Cocoa
import Carbon
import WebKit

@main struct AccessCheck {
    static func main() {
        _ = NSApplication.shared
        let state=URL(fileURLWithPath:"/tmp/quick-entry-access-"+UUID().uuidString)
        try! FileManager.default.createDirectory(at:state,withIntermediateDirectories:true)
        defer { try? FileManager.default.removeItem(at:state) }
        let entry=QuickEntry(state:state,base:URL(string:"http://127.0.0.1:8388/")!,web:WKWebView())
        assert(entry.binding == "cmd+shift+key:49","Only Command+Shift+Space should be configured by default")
        assert(entry.hotkey != nil,"Default hotkey must register")
        assert(entry.globalMonitor == nil && entry.localMonitor == nil,"Default must not monitor modifier-only gestures")
        assert(entry.read("quick-entry-status.json")?["registered"] as? Bool == true)
        var event: EventRef?
        CreateEvent(nil,OSType(kEventClassKeyboard),UInt32(kEventHotKeyPressed),0,0,&event)
        var id=EventHotKeyID(signature:0x56545145,id:1)
        SetEventParameter(event,EventParamName(kEventParamDirectObject),EventParamType(typeEventHotKeyID),
                          MemoryLayout<EventHotKeyID>.size,&id)
        SendEventToEventTarget(event,GetApplicationEventTarget())
        assert(entry.panel.isVisible,"Carbon hotkey event must open the bubble")
        ReleaseEvent(event)
        entry.close(cancel:true)
        assert(entry.register("ctrl+alt+key:49") == nil,"A custom chord replaces it")
        print("Single default registered and opened the panel; rebind passed. Accessibility:",AXIsProcessTrusted())
    }
}
