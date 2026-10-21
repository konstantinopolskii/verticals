/* Bindings for JSX: class and style values, attributes a parent puts on a component, fields and refs. `cx` takes a class
   value (strings, arrays, objects of class: condition), `sx` a style value (kebab-case and custom properties), and
   `fallthrough` puts a parent's attributes on a component's root: class and style merge into the root's, listeners run
   after the root's own, the rest replace. */
import type { CompositionEvent, CSSProperties, FormEvent } from 'react'
import { owners, type Ref } from './reactivity'

export type ClassValue = string | number | boolean | null | undefined | ClassValue[] | { [name: string]: unknown }

export function cx(...values: ClassValue[]): string {
  const out: string[] = []
  const add = (value: ClassValue): void => {
    if (!value || value === true || typeof value === 'number') return
    if (typeof value === 'string') out.push(value)
    else if (Array.isArray(value)) value.forEach(add)
    else for (const [name, on] of Object.entries(value)) if (on) out.push(name)
  }
  values.forEach(add)
  return out.join(' ').trim()
}

export type StyleValue = Record<string, string | number | null | undefined> | StyleValue[] | string | null | undefined | false

function camel(name: string): string {
  return name.startsWith('--') ? name : name.replace(/-([a-z])/g, (_, letter: string) => letter.toUpperCase())
}

/** Vue's style binding: a later value wins, an empty one takes the earlier away, and a number is set as it is (React
 *  would add `px` to it). */
export function sx(...values: StyleValue[]): CSSProperties {
  const out: Record<string, string> = {}
  const put = (name: string, v: string | number | null | undefined): void => {
    if (v == null || v === '') delete out[name]
    else out[name] = String(v)
  }
  const add = (value: StyleValue): void => {
    if (!value) return
    if (Array.isArray(value)) value.forEach(add)
    else if (typeof value === 'string') {
      for (const declaration of value.replace(/\/\*[^]*?\*\//g, '').split(/;(?![^(]*\))/g)) {
        const at = declaration.indexOf(':')
        if (at > 0) put(camel(declaration.slice(0, at).trim()), declaration.slice(at + 1).trim())
      }
    } else {
      for (const [name, v] of Object.entries(value)) put(camel(name), v)
    }
  }
  values.forEach(add)
  return out as CSSProperties
}

type Attrs = Record<string, unknown> & { className?: string; style?: CSSProperties }

export function fallthrough(own: Attrs, from: Attrs | undefined): Record<string, any> {
  if (!from) return own
  const merged: Attrs = { ...own }
  for (const [name, value] of Object.entries(from)) {
    // An attribute the parent leaves undefined still replaces the root's own, as Vue merges it; a class, a style, a
    // listener or a ref that is undefined adds nothing.
    if (value === undefined && (name === 'className' || name === 'style' || name === 'ref' || /^on[A-Z]/.test(name))) continue
    if (name === 'className') merged.className = cx(own.className, value as string)
    else if (name === 'style') merged.style = { ...own.style, ...(value as CSSProperties) }
    else if (name === 'ref' && own.ref) merged.ref = mergeRefs(own.ref as AnyRef, value as AnyRef)
    else if (/^on[A-Z]/.test(name) && typeof own[name] === 'function' && typeof value === 'function') {
      const first = own[name] as (...args: unknown[]) => void
      const second = value as (...args: unknown[]) => void
      merged[name] = (...args: unknown[]) => {
        first(...args)
        second(...args)
      }
    } else merged[name] = value
  }
  return merged
}

type TextField = HTMLInputElement | HTMLTextAreaElement
type Composing = TextField & { _composing?: boolean }

const composeEnds = new WeakSet<Element>()

function endComposing(event: Event): void {
  const el = event.target as Composing
  if (!el._composing) return
  el._composing = false
  el.dispatchEvent(new Event('input', { bubbles: true }))
}

function binding(value: string, element: Ref<TextField | null> | undefined, composed: boolean) {
  const bound = element ? bindRef(element) : undefined
  // A new callback on each drawing, so it runs after each one: the property takes the value where it differs. React
  // never writes it, so a textarea has no text of its own.
  return (el: TextField | null) => {
    if (el && !(composed && (el as Composing)._composing) && el.value !== value) el.value = value
    // A change ends a composition too, as v-model has it.
    if (el && composed && !composeEnds.has(el)) {
      composeEnds.add(el)
      el.addEventListener('change', endComposing)
    }
    const release = bound?.(el)
    return () => release?.()
  }
}

/** `:value` with `@input` on a text field: `onInput` hears each input; `element` is the field's template ref, if any. */
export function valueOf(value: string, onInput: (event: FormEvent<TextField>) => void, element?: Ref<TextField | null>) {
  return { ref: binding(value, element, false), onInput }
}

/** A text field bound both ways: the model takes each input, but none while an IME composes. */
export function model(value: Ref<string>, element?: Ref<TextField | null>) {
  return {
    ref: binding(value.value ?? '', element, true),
    onInput: (event: FormEvent<TextField>) => {
      if (!(event.currentTarget as Composing)._composing) value.value = event.currentTarget.value
    },
    onCompositionStart: (event: CompositionEvent<TextField>) => {
      ;(event.currentTarget as Composing)._composing = true
    },
    // The composed text comes in as an input, as v-model's does, so every input listener on the field hears it.
    onCompositionEnd: (event: CompositionEvent<TextField>) => endComposing(event.nativeEvent),
  }
}

const elementRefs = new WeakMap<object, (node: Element | null) => () => void>()

/** The template refs each component holds, by its number, and each element is in, for them to be let go of as the
 *  component ends or the element starts to leave. */
const held = new Map<number, Set<Ref<Element | null>>>()
const heldOn = new WeakMap<Element, Set<() => void>>()

/** How a ref on `node` lets go of it when the element starts to leave (src/Transition.tsx). */
export function onRelease(node: Element, release: () => void): void {
  if (!heldOn.has(node)) heldOn.set(node, new Set())
  heldOn.get(node)!.add(release)
}

/** A template ref (`ref="el"` on an element, or on a component for its root element): one callback per ref, so React
 *  does not hand it null and the node again on every drawing. It belongs to the component drawing it first. When an
 *  element goes, the ref is cleared only if it still holds that element: one that leaves after a new one came keeps the
 *  new one in the ref. */
export function bindRef<T extends Element>(target: Ref<T | null>): (node: T | null) => () => void {
  let set = elementRefs.get(target)
  if (!set) {
    const owner = owners[owners.length - 1]
    set = (node) => {
      target.value = node as T | null
      if (node) {
        if (owner !== undefined) {
          if (!held.has(owner)) held.set(owner, new Set())
          held.get(owner)!.add(target as Ref<Element | null>)
        }
        onRelease(node, () => {
          if (target.value === node) target.value = null
        })
      }
      return () => {
        if (target.value === node) target.value = null
      }
    }
    elementRefs.set(target, set)
  }
  return set
}

const keyedRefs = new WeakMap<object, Map<string, (node: Element | null) => () => void>>()

/** bindRef for one of the elements a ref holds by key, as a list's rows: one callback per key. */
export function bindRefAt<T extends Element>(target: Ref<Record<string, T | null>>, key: string): (node: T | null) => () => void {
  let byKey = keyedRefs.get(target)
  if (!byKey) keyedRefs.set(target, byKey = new Map())
  let set = byKey.get(key)
  if (!set) {
    set = (node) => {
      target.value[key] = node as T | null
      if (node) onRelease(node, () => {
        if (target.value[key] === node) target.value[key] = null
      })
      return () => {
        if (target.value[key] === node) target.value[key] = null
      }
    }
    byKey.set(key, set)
  }
  return set
}

/** A component that ends lets go of its template refs, as Vue's unmount does (src/setup.ts). */
export function releaseRefs(owner: number): void {
  for (const target of held.get(owner) ?? []) target.value = null
  held.delete(owner)
}

/** An element that starts to leave lets go of the template refs on it and in it, whoever draws them (src/Transition.tsx). */
export function releaseRefsIn(root: Element): void {
  for (const el of [root, ...root.querySelectorAll('*')]) {
    for (const release of heldOn.get(el) ?? []) release()
    heldOn.delete(el)
  }
}

type AnyRef = ((node: never) => void | (() => void)) | { current: unknown } | null | undefined

/** Hands `node` to a ref and gives back how to take it away again: the ref's own cleanup (React 19), or null for a
 *  callback without one, or clearing an object ref that still holds the node. */
export function attachRef(ref: AnyRef, node: unknown): () => void {
  if (typeof ref === 'function') {
    const cleanup = (ref as (node: unknown) => void | (() => void))(node)
    return typeof cleanup === 'function' ? cleanup : () => (ref as (node: unknown) => void)(null)
  }
  if (ref) {
    ref.current = node
    return () => {
      if (ref.current === node) ref.current = null
    }
  }
  return () => undefined
}

const merges = new WeakMap<object, WeakMap<object, (node: unknown) => () => void>>()

/** Two refs on one element (the root's own template ref and the parent's), as one callback that stays the same for the
 *  same pair. */
export function mergeRefs(first: AnyRef, second: AnyRef): (node: unknown) => () => void {
  const both = (node: unknown) => {
    const releases = [attachRef(first, node), attachRef(second, node)]
    return () => releases.forEach((release) => release())
  }
  if (!first || !second) return both
  let byFirst = merges.get(first)
  if (!byFirst) merges.set(first, (byFirst = new WeakMap()))
  let merged = byFirst.get(second)
  if (!merged) {
    merged = both
    byFirst.set(second, merged)
  }
  return merged
}
