@main struct Checks {
 static func main() {
  var tap = ModifierTap(required: 1)
  assert(!tap.flags(1))
  assert(tap.flags(0), "Fn alone must open after release")
  assert(!tap.flags(0), "No duplicate on repeated flags")
  _ = tap.flags(1); tap.key()
  assert(!tap.flags(0), "Fn+key must not open")
  _ = tap.flags(3)
  assert(!tap.flags(0), "Fn with another modifier must not open")
  _ = tap.flags(1); _ = tap.flags(3)
  _ = tap.flags(1)
  assert(!tap.flags(0), "Releasing modifier first still cancels")
  var chord = ModifierTap(required: 6) // Cmd=2, Shift=4
  assert(!chord.flags(2)); assert(!chord.flags(6))
  assert(!chord.flags(4)); assert(chord.flags(0), "Cmd+Shift fires only after both released")
  assert(!chord.flags(0))
  _ = chord.flags(4); _ = chord.flags(6); chord.key(); _ = chord.flags(2)
  assert(!chord.flags(0), "Cmd+Shift+letter must not open")
  _ = chord.flags(2); chord.key(); _ = chord.flags(6)
  assert(!chord.flags(0), "Typing before completing chord cancels")
  _ = chord.flags(6); _ = chord.flags(14); _ = chord.flags(6)
  assert(!chord.flags(0), "Extra modifier cancels")
  _ = chord.flags(2); assert(!chord.flags(0), "Single modifier does not open")
  print("Fn and modifier gesture checks passed")
 }
}
