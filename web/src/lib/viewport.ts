// The width of the app's window, for layouts that follow it.
import { reactive } from '../reactivity'

export const viewport = reactive({ width: typeof innerWidth === 'number' ? innerWidth : 1440 })

if (typeof window !== 'undefined') window.addEventListener('resize', () => { viewport.width = innerWidth })
