/* The agent's instructions in a window: for each layer, the text built into the app, read-only, and the memory after it. */
import type { MouseEvent } from 'react'
import { onMounted, ref, watch } from '../reactivity'
import { fetchInstructions, INSTRUCTIONS_KEY, openMemory, type MemoryLayer } from '../lib/agentMemory'
import { renderBodyElement } from '../lib/bodyMarkdown'
import { frontWindow } from '../lib/windows'
import { bindRef, fallthrough } from '../bind'
import { tracked } from '../tracked'
import { useSetup } from '../setup'
import './instructionsWindowBody.css'

const MemoryText = tracked(function MemoryText({ text }: { text: string }) {
  const s = useSetup({ text }, (props) => {
    const el = ref<HTMLElement | null>(null)
    function render(): void {
      if (!el.value) return
      el.value.replaceChildren()
      renderBodyElement(el.value, props.text)
    }
    onMounted(render)
    watch(() => props.text, render)
    return { el }
  })
  return <div ref={bindRef(s.el)} className="goal-detail__body agent-memory__text" />
})

export const InstructionsWindowBody = tracked(function InstructionsWindowBody(attrs: Record<string, unknown>) {
  const s = useSetup({}, () => {
    const layers = ref<MemoryLayer[] | null>(null)
    const failed = ref(false)

    async function load(): Promise<void> {
      try {
        layers.value = await fetchInstructions()
        failed.value = false
      } catch {
        failed.value = true
      }
    }
    function onEdit(event: MouseEvent<HTMLButtonElement>): void {
      const layer = layers.value?.find((l) => l.id === event.currentTarget.dataset.layer)
      if (layer) void openMemory(layer, event.currentTarget)
    }
    onMounted(load)
    // Back from editing a document, the window reads the memory again.
    watch(() => frontWindow.value?.key, (key) => { if (key === INSTRUCTIONS_KEY) void load() })
    return { layers, failed, onEdit }
  })
  const layers = s.layers.value
  return (
    <div {...fallthrough({ className: 'agent-memory', 'data-role': 'agent-memory' }, attrs)}>
      <p className="agent-memory__lead">
        Memory comes after the built-in instructions and wins where they differ. You write it, and so does the agent when you
        correct it. The built-in part updates with the app and can't be edited.
      </p>
      {s.failed.value ? <p className="agent-memory__note">The instructions could not be read.</p>
        : !layers ? <p className="agent-memory__note">Loading…</p> : layers.map((layer) => (
          <section key={layer.id} className="agent-memory__layer" data-layer={layer.id}>
            <h3 className="agent-memory__title">{layer.title}</h3>
            <details className="agent-memory__built-in" data-role="agent-memory-built-in">
              <summary className="agent-memory__label">Built into Verticals, read-only</summary>
              <MemoryText text={layer.builtIn} />
            </details>
            <div className="agent-memory__yours" data-role="agent-memory-yours">
              <h4 className="agent-memory__label">Memory</h4>
              {layer.memory.body?.trim() ? <MemoryText text={layer.memory.body} />
                : <p className="agent-memory__note">None yet.</p>}
              <button type="button" className="agent-memory__edit" data-layer={layer.id} data-role="agent-memory-edit"
                onClick={s.onEdit}>{layer.memory.id ? 'Edit' : 'Write'}</button>
            </div>
          </section>
        ))}
    </div>
  )
})
