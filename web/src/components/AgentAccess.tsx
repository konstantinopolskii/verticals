import { useEffect, useRef } from 'react'
import { agentChat, chooseInitialAccess } from '../lib/agentChat'
import { tracked } from '../tracked'
import './agentAccess.css'

export const AgentAccess = tracked(function AgentAccess() {
  const dialog = useRef<HTMLDialogElement>(null)
  const needed = agentChat.available && !agentChat.accessChosen
  useEffect(() => {
    if (needed) dialog.current?.showModal()
  }, [needed])
  if (!needed) return null
  return (
    <dialog ref={dialog} className="agent-access" aria-labelledby="agent-access-title"
      onCancel={(event) => event.preventDefault()}>
      <h1 id="agent-access-title">Agent access</h1>
      <p>Allow Claude and Codex to read and change files anywhere on this Mac, run terminal commands,
        use the network and connected tools without asking again?</p>
      <p>This also applies to morning reports. You can change access in the agent menu.
        macOS permissions and account sign-ins still apply.</p>
      <div className="agent-access__actions">
        <button type="button" onClick={() => chooseInitialAccess(false)}>Keep asking</button>
        <button type="button" className="agent-access__allow" onClick={() => chooseInitialAccess(true)}>Allow full access</button>
      </div>
    </dialog>
  )
})
