/* The agent tag above the field: the agent's mark and a chevron, its menu the agent picker (agent, model, effort, speed,
   permissions, usage) with "New conversation" and "Instructions" on top. */
import type { KeyboardEvent } from 'react'
import { computed, onBeforeUnmount, ref } from '../reactivity'
import { AppIcon } from './AppIcon'
import { agentChat, agentOf, assetUrl, choose, loadProbe, newThread, refreshAgents, type ModelChoice, type Probe } from '../lib/agentChat'
import { openInstructions } from '../lib/agentMemory'
import { bindRef, fallthrough, sx } from '../bind'
import { tracked } from '../tracked'
import { useSetup } from '../setup'
import './agentTag.css'

export const AgentTag = tracked(function AgentTag(attrs: Record<string, unknown>) {
  const s = useSetup({}, () => {
    const open = ref(false)
    const root = ref<HTMLElement | null>(null)
    const hoverDetail = ref<string | null>(null)
    const selection = computed(() => agentChat.selection)
    const agent = computed(() => agentOf(selection.value?.provider))
    const probe = computed<Probe>(() => agentChat.probes[selection.value?.provider ?? ''] ?? { models: [] })
    const models = computed<ModelChoice[]>(() => {
      const list = probe.value.models ?? []
      const saved = selection.value?.model
      return saved && !list.some((model) => model.value === saved) ? [{ value: saved, label: saved, detail: 'Your saved choice' }, ...list] : list
    })
    const permission = computed(() => agent.value.permissions.find((p) => p.value === selection.value?.permission))
    const footer = computed(() => hoverDetail.value || permission.value?.detail || 'Applies to your next message.')

    function toggle(): void {
      open.value = !open.value
      if (!open.value) return
      hoverDetail.value = null
      if (selection.value) void loadProbe(selection.value.provider, true)
      void refreshAgents()
      document.addEventListener('pointerdown', onOutside, true)
    }
    function close(): void {
      open.value = false
      document.removeEventListener('pointerdown', onOutside, true)
    }
    function onOutside(event: PointerEvent): void {
      if (!root.value?.contains(event.target as Node)) close()
    }
    function startNew(): void {
      newThread()
      agentChat.history = []
      close()
    }
    function showInstructions(): void {
      close()
      openInstructions(root.value)
    }
    onBeforeUnmount(() => document.removeEventListener('pointerdown', onOutside, true))
    return { open, root, hoverDetail, selection, agent, probe, models, footer, toggle, close, startNew, showInstructions }
  })

  const selection = agentChat.available && s.selection.value
  if (!selection) return null
  const agent = s.agent.value
  const probe = s.probe.value
  const models = s.models.value
  const hover = (detail: string | null) => () => {
    s.hoverDetail.value = detail
  }
  function onEsc(event: KeyboardEvent): void {
    if (event.key !== 'Escape') return
    event.stopPropagation()
    s.close()
  }

  return (
    <div {...fallthrough({ ref: bindRef(s.root), className: 'agent-tag-wrap' }, attrs)}>
      <button
        type="button"
        className="circle-tag agent-tag"
        data-tag="agent"
        aria-label={`Agent: ${agent.label}`}
        aria-expanded={s.open.value}
        onClick={s.toggle}
        onKeyDown={onEsc}
      >
        <img className="agent-tag__mark" alt="" src={assetUrl(agent.image)} />
        <span className="circle-tag__name">{agent.label.replace(' Code', '')}</span>
        <AppIcon name="chevron-down" size={12} stroke={2.6} />
      </button>
      {s.open.value ? (
        <div className="agent-picker vt-shadow vt-shadow--small" role="dialog" aria-label="Agent settings" onKeyDown={onEsc}>
          <button type="button" className="agent-picker__new" data-role="new-conversation" onClick={s.startNew}>
            <AppIcon name="plus" size={14} />{' New conversation '}
          </button>
          <button type="button" className="agent-picker__new" data-role="agent-instructions" onClick={s.showInstructions}>
            <AppIcon name="file" size={14} />{' Instructions '}
          </button>
          <div className="agent-picker__columns">
            <section>
              <h2>Agent</h2>
              {agentChat.agents.map((item) => (
                <div key={item.id}>
                  <button type="button" className="agent-picker__choice" aria-pressed={item.id === selection.provider}
                    disabled={!item.available} onClick={() => choose({ provider: item.id })}>
                    <img alt="" src={assetUrl(item.image)} /><span>{item.label}{!item.available ? <small>Not installed</small> : null}</span>
                  </button>
                  {item.id === selection.provider ? (
                    <div className="agent-picker__usage">
                      {!probe.usage || probe.loading ? <p>Loading usage…</p>
                        : probe.usage.state !== 'ready' ? <p>Usage unavailable</p>
                        : (probe.usage.windows ?? []).map((w) => (
                          <div key={w.label} className="agent-picker__quota">
                            <span>{w.label}</span><span>{`${w.remainingPercent}% left`}</span>
                            <i style={sx({ width: `${w.remainingPercent}%` })}></i>
                          </div>
                        ))}
                    </div>
                  ) : null}
                </div>
              ))}
            </section>
            <section>
              <h2>Model</h2>
              {probe.loading && !models.length ? <p className="agent-picker__status">Loading models…</p>
                : !models.length ? <p className="agent-picker__status">No models available</p> : null}
              {models.map((model) => (
                <button key={model.value} type="button" className="agent-picker__choice"
                  aria-pressed={model.value === selection.model} disabled={!!probe.loading}
                  onMouseEnter={hover(model.detail || null)} onClick={() => choose({ model: model.value })}>
                  <span>{model.label}</span>
                </button>
              ))}
              {probe.modelsError ? <p className="agent-picker__status">{probe.modelsError}</p> : null}
            </section>
            <section>
              <h2>Effort</h2>
              {agent.efforts.map((effort) => (
                <button key={effort.value} type="button" className="agent-picker__choice"
                  aria-pressed={effort.value === selection.effort} onClick={() => choose({ effort: effort.value })}>
                  <span>{effort.label}</span>
                </button>
              ))}
            </section>
            <section>
              <h2>Speed</h2>
              <button type="button" className="agent-picker__choice" aria-pressed={!selection.fast}
                onClick={() => choose({ fast: false })}><span>Standard</span></button>
              <button type="button" className="agent-picker__choice" aria-pressed={selection.fast}
                onMouseEnter={hover(agent.fast || null)} onClick={() => choose({ fast: true })}><span>Fast</span></button>
            </section>
            <section>
              <h2>Permissions</h2>
              {agent.permissions.map((p) => (
                <button key={p.value} type="button" className="agent-picker__choice"
                  aria-pressed={p.value === selection.permission} onMouseEnter={hover(p.detail)}
                  onClick={() => choose({ permission: p.value })}>
                  <span>{p.label}</span>
                </button>
              ))}
            </section>
          </div>
          <p className="agent-picker__footer">{s.footer.value}</p>
        </div>
      ) : null}
    </div>
  )
})
