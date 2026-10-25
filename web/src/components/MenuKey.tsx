/* The key that picks a menu item, grey at the item's right (PopoverEngine.tsx reads the item's `data-key`). Drawn by CSS,
   so the item's words stay its words. */
import './menuKey.css'

export function MenuKey({ label }: { label: string }) {
  return <kbd className="menu-key" data-label={label} aria-hidden="true" />
}
