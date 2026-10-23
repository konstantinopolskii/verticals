// A modifier-only gesture fires after all keys are released, unless another input intervened.
struct ModifierTap {
    let required: UInt
    init(required: UInt) { self.required = required }
    private var held = false
    private var armed = false
    private var cancelled = false
    mutating func flags(_ mask: UInt) -> Bool {
        if mask == 0 {
            let fire = armed && !cancelled
            held = false; armed = false; cancelled = false
            return fire
        }
        held = true
        if mask & ~required != 0 { cancelled = true }
        if mask == required { armed = true }
        return false
    }
    mutating func key() { if held { cancelled = true } }
}
