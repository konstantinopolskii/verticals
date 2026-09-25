// Verticals chat: a bar at the bottom centre that opens into a conversation with a local agent.
// The conversation view, composer and agent picker are ported from Enjoy (markup, styles,
// strings, behaviour); agents work on the board through the Verticals MCP server.
(() => {
  if (window.__vtChat) return;
  window.__vtChat = true;

  // ---------------------------------------------------------------- state

  const store = {
    get(key, fallback) { try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } },
    set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch {} },
  };
  const uuid = () => crypto.randomUUID();
  let threads = store.get('vt-chat:threads', []);             // [{id,title,provider,updatedAt,status}]
  let current = store.get('vt-chat:current', null);
  let history = [];
  let cursor = { boot: null, seq: 0 };
  let agents = [];
  const probes = {};                                          // provider -> {models, usage, loading}
  let selection = null;                                       // {provider, model, effort, fast, permission}
  let running = false, expanded = false, lastSelection = '', stream = null;
  let pendingGoal = null;   // goal of a conversation opened from a card, until its first message

  // ---------------------------------------------------------------- icons (lucide, as in Enjoy)

  const icon = (d, size = 16, extra = '') => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ${extra}>${d}</svg>`;
  const I = {
    chevron: '<path d="m6 9 6 6 6-6"/>', up: '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
    check: '<path d="M20 6 9 17l-5-5"/>', plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
    list: '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/>',
    clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>', bolt: '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
    user: '<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    tool: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
    lock: '<rect width="18" height="11" x="3" y="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    alert: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
    panel: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M15 3v18"/>',
    target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    message: '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>',
  };
  const stopSvg = '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>';

  // ---------------------------------------------------------------- DOM + Enjoy styles (light theme)

  const host = document.createElement('div');
  host.id = 'vt-chat';
  const root = host.attachShadow({ mode: 'open' });
  root.innerHTML = `
<style>
  :host { all: initial; }
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  .wrap {
    --logo-blue:#2878ef; --logo-orange:#f58220; --logo-pink:#f06aa8; --soft-orange:#ffd392; --soft-pink:#ffcbe2; --orange-ink:#9b4a10;
    --canvas:#fafaf9; --panel:#fff; --field-bg:#f0f0eb; --strong:#242523; --text:#353630; --body:#353630; --muted:#72736d;
    --surface-border:#e5e5df; --surface-strong:#e5e5df; --timestamp:#72736d; --subtle-surface:#f5f5f1; --input-border:#cdcec5;
    --muted-detail:#72736d; --panel-shadow:#0002; --button-bg:var(--logo-blue); --button-fg:#fff; --success:#2f8a5b; --error-fg:#c2362b;
    --project-accent:#215fae; --font:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
    --agent-usage-accent:color-mix(in srgb,var(--logo-blue) 70%,var(--strong));
    position: fixed; left: 50%; bottom: 18px; transform: translateX(-50%); z-index: 2147483000;
    font: 14px/1.45 var(--font); color: var(--strong); width: min(560px, calc(100vw - 32px));
  }
  .wrap.open { width: min(880px, calc(100vw - 32px)); }
  .wrap.open.with-sidebar { width: min(1180px, calc(100vw - 32px)); }
  button { font: inherit; color: inherit; background: none; border: 0; cursor: pointer; }
  button:disabled { cursor: default; }

  /* collapsed bar */
  .bar { display:flex; align-items:center; gap:10px; height:46px; padding:0 8px 0 14px; background:var(--panel); border:1px solid var(--surface-border);
    border-radius:23px; box-shadow:0 12px 40px #0002,0 2px 8px #0001; cursor:text; }
  .bar img { width:18px; height:18px; }
  .bar input { flex:1; border:0; background:none; font:inherit; color:var(--strong); outline:none; min-width:0; }
  .bar kbd { font:11px var(--font); color:var(--muted); border:1px solid var(--surface-border); border-radius:5px; padding:1px 5px; }
  .bar .badge { font-size:11px; color:#fff; background:var(--logo-blue); border-radius:999px; padding:1px 7px; }
  .open .bar { display:none; }

  /* panel */
  .panel { display:none; flex-direction:row; position:relative; height:min(78vh, 760px); background:var(--canvas);
    border:1px solid var(--surface-border); border-radius:16px; box-shadow:0 18px 60px #0003,0 2px 8px #0001; overflow:hidden; }
  .open .panel { display:flex; }
  .conv-main { flex:1; min-width:0; display:flex; flex-direction:column; position:relative; }
  .conv-sidebar { width:300px; flex:none; display:flex; flex-direction:column; border-right:1px solid var(--surface-border); background:var(--panel); min-height:0; }
  .conv-sidebar-head { display:flex; align-items:center; gap:8px; padding:14px 12px 10px 16px; }
  .conv-sidebar-head h2 { flex:1; margin:0; font:600 17px/1.3 var(--font); }
  .conv-new-round { width:30px; height:30px; border-radius:9px; display:grid; place-items:center; background:var(--logo-blue); color:#fff; }
  .conversation-filters { display:flex; gap:2px; padding:0 10px 8px; border-bottom:1px solid var(--surface-border); }
  .conversation-filters button { padding:5px 8px; border-radius:7px; font-size:11px; color:var(--muted); }
  .conversation-filters button[aria-pressed=true] { color:var(--strong); background:var(--field-bg); font-weight:500; }
  .conversation-filters small { margin-left:3px; }
  .conv-items { flex:1; min-height:0; overflow:auto; padding:8px; display:flex; flex-direction:column; gap:4px; }
  .conv-item { display:block; width:100%; text-align:left; padding:10px 12px; border-radius:12px; }
  .conv-item:hover { background:var(--subtle-surface); }
  .conv-item[aria-current=true] { background:var(--field-bg); }
  .conv-item strong { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; font:500 14px/1.4 var(--font); color:var(--strong); margin-top:2px; }
  .conv-item .meta { display:flex; justify-content:space-between; align-items:center; gap:8px; margin-top:6px; font-size:12px; color:var(--muted); }
  .thread-label { display:inline-block; max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; padding:1px 7px; border-radius:6px;
    font-size:12px; font-weight:500; color:#1f5f93; background:#dcecfb; margin-bottom:4px; }
  .conv-empty { padding:14px; color:var(--muted); font-size:13px; }
  .conv-header { display:flex; align-items:center; gap:8px; padding:10px 12px 10px 16px; border-bottom:1px solid var(--surface-border); background:var(--panel); }
  .conv-title { flex:1; min-width:0; }
  .conv-title h1 { margin:0; font:600 15px/1.35 var(--font); color:var(--strong); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .conv-status { display:flex; align-items:center; gap:5px; font-size:10px; color:var(--muted); margin-top:2px; }
  .icon-button { width:28px; height:28px; border-radius:7px; display:grid; place-items:center; color:var(--muted); flex:none; }
  .icon-button:hover { background:var(--surface-strong); color:var(--strong); }
  .stop-thread-button { display:inline-flex; align-items:center; justify-content:center; width:28px; height:28px; border:1px solid var(--surface-border);
    border-radius:7px; background:var(--surface-strong); color:var(--strong); }
  .stop-thread-button:hover { background:#d9d9d2; }
  .conversation-badge { display:inline-flex; align-items:center; gap:5px; padding:2px 7px; border-radius:6px; font-size:11px; background:var(--field-bg); color:var(--muted); white-space:nowrap; }
  .conversation-badge.is-running { color:#8a4b12; background:color-mix(in srgb,var(--soft-orange) 25%,transparent); }
  .conversation-badge.is-failed { color:var(--error-fg); background:#fdecea; }
  .conversation-badge.is-blocked { color:#8a4b12; background:color-mix(in srgb,var(--soft-orange) 25%,transparent); }

  /* transcript (Enjoy .workspace-transcript) */
  .workspace-transcript { flex:1; overflow-y:auto; display:flex; flex-direction:column; gap:23px; padding:20px 16px; }
  .message-meta { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:0 0 9px; font-size:12px; }
  .message-meta strong { color:var(--muted); font-weight:400; font-size:13px; }
  .message-meta time { color:var(--timestamp); }
  .message-user-avatar { width:28px; height:28px; display:inline-grid; place-items:center; color:color-mix(in srgb,var(--soft-pink) 40%,var(--muted)); border-radius:10px; flex:none; }
  .message-agent-avatar { width:28px; height:28px; border-radius:10px; flex:0 0 28px; object-fit:contain; }
  .message-work-time { color:var(--muted); font-size:10px; line-height:1.4; }
  .message-model-info { display:inline-flex; gap:6px; color:var(--muted); font-size:10px; }
  .message-model-info span + span:before { content:"·"; margin-right:6px; }
  .message-bubble { position:relative; width:fit-content; max-width:100%; padding:14px 16px; border-radius:6px 22px 22px;
    border:1px solid var(--surface-border); background:var(--canvas); }
  .outgoing .message-bubble { background:color-mix(in srgb,var(--soft-orange) 3%,var(--panel)); }
  .message-markdown { font-size:14px; line-height:1.6; color:var(--body); white-space:normal; overflow-wrap:anywhere; }
  .outgoing .message-markdown { color:var(--strong); white-space:pre-wrap; }
  .message-markdown > * + * { margin-top:.75em; }
  .message-markdown > :first-child { margin-top:0; }
  .message-markdown p { margin:0; }
  .message-markdown :is(ul,ol) { padding-left:1.5em; margin:0; }
  .message-markdown li + li { margin-top:.25em; }
  .message-markdown a { color:inherit; text-decoration:underline; text-underline-offset:3px; }
  .message-markdown code { font:.9em ui-monospace,SFMono-Regular,Menlo,monospace; background:color-mix(in srgb,var(--body) 8%,transparent); border-radius:4px; padding:.1em .3em; }
  .message-markdown pre { margin:0; max-width:100%; overflow-x:auto; white-space:pre; padding:10px; border-radius:8px; background:color-mix(in srgb,var(--body) 8%,transparent); }
  .message-markdown pre code { padding:0; background:none; }
  .message-markdown table { border-collapse:collapse; font-size:13px; }
  .message-markdown td, .message-markdown th { border:1px solid var(--surface-border); padding:4px 8px; text-align:left; }
  .message-markdown :is(h3,h4,h5,h6,h7,h8) { margin-bottom:0; font-size:1.05em; line-height:1.4; }
  .message-markdown blockquote { margin:0; padding-left:.8em; border-left:3px solid var(--muted-detail); color:var(--muted); }
  .message-markdown hr { border:0; border-top:1px solid var(--surface-border); }
  .message-markdown img { max-width:100%; height:auto; border-radius:8px; }
  .message-markdown li > :is(ul,ol) { margin-top:.25em; }
  .message-markdown input[type=checkbox] { margin:0 4px 0 0; vertical-align:-1px; }
  .message-markdown a[data-app-link] { color:var(--project-accent); text-decoration-color:color-mix(in srgb,var(--project-accent) 45%,transparent); }
  .system-message { color:var(--muted); font-size:14px; }
  .system-message.error { color:var(--error-fg); white-space:pre-wrap; }
  .empty { margin:auto; text-align:center; color:var(--muted); max-width:380px; font-size:13px; }
  .empty b { display:block; color:var(--strong); font:600 17px/1.4 var(--font); margin-bottom:6px; }

  /* working indicator + activity (Enjoy .message-working-indicator / .tool-activity) */
  .message-working-indicator { display:block; width:fit-content; max-width:100%; margin-top:2px; padding:0; border-radius:20px; background:transparent; }
  .message-working-indicator .conversation-badge { padding:4px 8px; border-radius:20px; font-size:12px; gap:5px; max-width:100%; }
  .message-working-indicator:hover .conversation-badge { background:var(--field-bg); }
  .working-timer { font-variant-numeric:tabular-nums; }
  .working-timer:before, .working-activity:before { content:"·"; margin-right:5px; }
  .working-activity { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .working-spinner { position:relative; display:inline-block; width:13px; height:13px; flex:none; }
  .working-spinner > i { display:block; position:absolute; width:82%; height:22%; left:9%; border-radius:24%; transform:rotate(-12deg);
    animation:working-stack 1.2s cubic-bezier(.45,0,.25,1) infinite; }
  .working-spinner > i:nth-child(1) { top:5%; background:var(--logo-blue); animation-delay:-.8s; }
  .working-spinner > i:nth-child(2) { top:39%; background:var(--logo-orange); animation-delay:-.4s; }
  .working-spinner > i:nth-child(3) { top:73%; background:var(--logo-pink); }
  @keyframes working-stack { 0%,100% { transform:rotate(-12deg) translateX(0); opacity:1; } 50% { transform:rotate(-12deg) translateX(18%); opacity:.55; } }
  .activity { display:flex; flex-direction:column; gap:8px; margin:0 0 10px; }
  .activity[hidden] { display:none; }
  .tool-activity { border:1px solid var(--surface-border); border-radius:12px; background:var(--panel); overflow:hidden; }
  .tool-activity summary { display:flex; align-items:flex-start; gap:9px; padding:10px 11px; cursor:pointer; list-style:none; }
  .tool-activity summary:hover { background:var(--subtle-surface); }
  .tool-activity summary::-webkit-details-marker { display:none; }
  .tool-activity-icon { color:var(--muted); margin-top:2px; }
  .tool-activity-label { flex:1; min-width:0; display:flex; flex-direction:column; gap:3px; }
  .tool-activity-label > span { font-size:11px; color:var(--muted); }
  .tool-activity-label > strong { font:500 13px/1.4 var(--font); overflow-wrap:anywhere; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
  .tool-activity-state { align-self:center; color:var(--muted); display:flex; }
  .tool-activity[open] .tool-activity-state svg { transform:rotate(180deg); }
  .tool-activity.is-failed { border-color:color-mix(in srgb,var(--error-fg) 40%,var(--surface-border)); }
  .tool-activity.is-failed .tool-activity-label > span { color:var(--error-fg); }
  .tool-activity.is-running .tool-activity-label > span { color:var(--logo-blue); }
  .tool-activity-body { padding:11px; border-top:1px solid var(--surface-border); background:var(--subtle-surface); }
  .tool-activity-body pre { margin:0; font:11px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace; white-space:pre-wrap; overflow-wrap:anywhere; max-height:240px; overflow:auto; color:var(--muted); }

  .agent-activity { position:absolute; top:51px; right:0; bottom:0; z-index:4; width:min(410px, 100%); display:flex; flex-direction:column;
    background:var(--canvas); border-left:1px solid var(--surface-border); box-shadow:-10px 0 45px var(--panel-shadow); }
  .agent-activity[hidden] { display:none; }
  .agent-activity-header { display:flex; align-items:center; gap:10px; padding:14px 14px 12px 18px; border-bottom:1px solid var(--surface-border); }
  .agent-activity-header h2 { flex:1; margin:0; font:600 15px/1.3 var(--font); }
  .agent-activity-scroll { flex:1; min-height:0; overflow:auto; padding:16px 18px; display:flex; flex-direction:column; gap:12px; }
  .activity-session-heading { display:flex; justify-content:space-between; gap:8px; font-size:11px; color:var(--muted); margin-top:6px; }
  .activity-empty { color:var(--muted); font-size:13px; text-align:center; padding:40px 10px; }
  .workspace-activity-toggle[aria-expanded=true] { color:var(--logo-blue); }

  /* decisions (Enjoy .decision-option) */
  .decision { padding:14px 16px; border:1px solid var(--surface-border); border-radius:12px; background:var(--panel); }
  .decision h3 { margin:0; font:600 14px/1.5 var(--font); color:var(--strong); }
  .decision pre { margin:8px 0 0; font:11px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace; white-space:pre-wrap; overflow-wrap:anywhere; color:var(--muted); max-height:200px; overflow:auto; }
  .decision-options { display:flex; flex-direction:column; gap:8px; margin:14px 0 0; }
  .decision-option { display:flex; align-items:center; gap:10px; min-height:44px; border:1px solid var(--surface-border); border-radius:10px; padding:10px 12px;
    color:var(--body); line-height:1.5; text-align:left; }
  .decision-option:hover:not(:disabled) { background:var(--field-bg); border-color:var(--input-border); }
  .decision-option i { flex:0 0 18px; width:18px; height:18px; border:1.5px solid var(--muted-detail); border-radius:50%; }
  .decision-option.selected { border-color:var(--logo-blue); background:color-mix(in srgb,var(--logo-blue) 8%,var(--panel)); color:var(--strong); }
  .decision-option.selected i { border-color:var(--logo-blue); background:var(--logo-blue); box-shadow:inset 0 0 0 4px var(--panel); }
  .decision.resolved .decision-option:not(.selected) { opacity:.5; }

  /* composer (Enjoy .composer[data-agent-toolbar]) */
  .workspace-composer { padding:8px 14px 12px; position:relative; }
  .composer { display:flex; flex-direction:column; border:1px solid var(--surface-border); border-radius:14px; background:var(--panel); }
  .composer:focus-within { border-color:color-mix(in srgb,var(--muted) 55%,var(--surface-border)); }
  .composer-recipes { display:flex; flex-wrap:wrap; gap:6px; padding:8px 10px 0; }
  .composer-chip { display:inline-flex; align-items:center; gap:6px; max-width:100%; padding:3px 6px 3px 9px; border-radius:8px; background:var(--field-bg); font-size:12px; color:var(--strong); }
  .composer-chip span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .composer-chip small { color:var(--muted); }
  .composer-selection { display:flex; gap:6px; align-items:center; font-size:12px; color:var(--muted); padding:8px 13px 0; }
  .composer-selection span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .composer textarea { width:100%; resize:none; border:0; outline:none; background:transparent; padding:11px 13px; font:14px/22px var(--font);
    color:var(--strong); min-height:44px; max-height:min(180px,30dvh); }
  .composer textarea::placeholder { color:var(--muted); }
  .composer-footer { display:flex; align-items:center; gap:5px; padding:4px 7px 6px; border-top:1px solid var(--surface-border); background:var(--canvas); border-radius:0 0 13px 13px; }
  .send-button { margin-left:auto; width:30px; height:30px; border-radius:7px; display:grid; place-items:center; background:var(--button-bg); color:var(--button-fg); }
  .send-button:disabled { background:var(--surface-strong); color:var(--muted); }
  .composer-queue-action { width:auto; padding:0 8px; display:inline-flex; align-items:center; background:var(--surface-strong); color:var(--strong); margin-left:auto; }
  .composer-queue-action:not([hidden]) + .send-button { margin-left:0; }
  .composer-send-label { max-width:0; opacity:0; overflow:hidden; white-space:nowrap; font-size:12px; font-weight:600; transition:max-width .16s,opacity .12s,margin .16s; }
  .composer-queue-action:hover .composer-send-label { max-width:50px; opacity:1; margin-left:5px; }

  /* agent picker trigger + popover (Enjoy .agent-settings-*) */
  .agent-settings-trigger { display:flex; align-items:center; gap:5px; max-width:360px; min-height:38px; padding:3px 6px; border-radius:6px; text-align:left; color:var(--muted); }
  .agent-settings-trigger:hover, .agent-settings-trigger[data-state=open] { background:var(--surface-strong); }
  .agent-settings-trigger > img { width:16px; height:16px; flex:0 0 16px; }
  .agent-settings-summary { display:grid; min-width:0; gap:1px; }
  .agent-settings-summary-top { display:flex; align-items:center; flex-wrap:wrap; gap:3px 8px; }
  .agent-settings-summary-agent { font-size:13px; font-weight:550; color:var(--strong); }
  .agent-settings-summary-details { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:11px; line-height:1.5; color:var(--muted); }
  .agent-settings-badge { display:inline-flex; align-items:center; gap:4px; padding:1px 5px; border-radius:4px; background:var(--field-bg); color:var(--text); font-size:11px; font-weight:500; line-height:15px; }
  .agent-settings-badge-fast { color:var(--project-accent); }
  .joy-select-chevron { display:flex; color:var(--muted); }
  .agent-settings-picker { position:absolute; left:12px; right:12px; bottom:calc(100% - 4px); z-index:6; display:flex; flex-direction:column; max-height:min(480px, 62vh);
    overflow:hidden; border:1px solid var(--surface-border); border-radius:14px; background:var(--panel); color:var(--strong);
    box-shadow:0 12px 40px #0003,0 2px 8px #0002; font:12px/1.4 var(--font); }
  .agent-settings-picker[hidden] { display:none; }
  .agent-settings-scroll { flex:1; min-height:0; overflow:auto; }
  .agent-settings-columns { display:grid; height:100%; grid-template-columns:minmax(160px,1.3fr) minmax(140px,1.2fr) minmax(95px,.85fr) minmax(95px,.85fr) minmax(150px,1.4fr);
    min-width:718px; padding:14px 8px; }
  .agent-settings-column { display:flex; flex-direction:column; min-height:0; min-width:0; padding:0 6px; overflow-y:auto; }
  .agent-settings-column + .agent-settings-column { border-left:1px solid var(--surface-border); }
  .agent-settings-column h2 { padding:0 6px; margin:0 0 10px; font:500 11px/1.4 var(--font); color:var(--muted); }
  .agent-settings-choice { display:flex; align-items:center; gap:5px; width:100%; min-height:32px; padding:6px; margin:1px 0; border-radius:6px; color:var(--strong); font-size:11px; text-align:left; }
  .agent-settings-choice > span { flex:1; min-width:0; }
  .agent-settings-agent .agent-settings-choice { font-size:14px; font-weight:550; }
  .agent-settings-agent .agent-settings-choice > span { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .agent-settings-choice img { width:16px; height:16px; object-fit:contain; border-radius:4px; flex:none; }
  .agent-settings-choice .check { color:var(--agent-usage-accent); display:flex; }
  .agent-settings-choice small { display:block; color:var(--muted); font-size:10px; font-weight:400; }
  .agent-settings-choice[aria-pressed=true] { background:color-mix(in srgb,var(--logo-blue) 12%,var(--panel)); }
  .agent-settings-agent .agent-settings-choice[aria-pressed=true] { box-shadow:inset 0 0 0 1.5px var(--logo-blue); }
  .agent-settings-choice:hover:not(:disabled) { background:color-mix(in srgb,var(--logo-blue) 18%,var(--panel)); }
  .agent-settings-choice:disabled { opacity:.45; }
  .agent-settings-status { margin:6px; color:var(--muted); font-size:11px; }
  .agent-settings-quota { padding:4px 6px 10px; display:flex; flex-direction:column; gap:6px; }
  .agent-settings-quota-row { display:flex; justify-content:space-between; font-size:10px; color:var(--muted); }
  .agent-settings-quota-track { height:3px; background:color-mix(in srgb,var(--muted) 18%,transparent);
    mask:repeating-linear-gradient(90deg,#000 0 calc(10% - 2px),transparent calc(10% - 2px) 10%); -webkit-mask:repeating-linear-gradient(90deg,#000 0 calc(10% - 2px),transparent calc(10% - 2px) 10%); }
  .agent-settings-quota-track > i { display:block; height:100%; background:var(--agent-usage-accent); }
  .agent-settings-footer { display:flex; flex-wrap:wrap; justify-content:flex-end; align-items:center; gap:8px; padding:8px 12px; border-top:1px solid var(--surface-border); }
  .agent-settings-footer p { flex:1 1 260px; margin:0; font-size:10px; color:var(--muted); }
  .agent-settings-close-after-selection { display:flex; align-items:center; gap:6px; color:var(--muted); font-size:10px; }
</style>
<div class="wrap">
  <div class="bar">
    <img alt="" class="bar-agent">
    <input placeholder="Ask your agent to do anything..." aria-label="Message">
    <span class="badge" hidden>Needs you</span>
    <kbd>⌘K</kbd>
  </div>
  <section class="panel" role="dialog" aria-label="Conversation">
    <aside class="conv-sidebar" hidden>
      <div class="conv-sidebar-head"><h2>Conversations</h2><button class="conv-new-round" title="New conversation">${icon(I.plus)}</button></div>
      <div class="conversation-filters"></div>
      <div class="conv-items"></div>
    </aside>
    <div class="conv-main">
    <header class="conv-header">
      <div class="conv-title"><h1>New conversation</h1><div class="conv-status"></div></div>
      <button class="stop-thread-button" aria-label="Stop work" title="Stop work" hidden>${stopSvg}</button>
      <button class="icon-button workspace-activity-toggle" title="Agent activity" aria-expanded="false">${icon(I.panel)}</button>
      <button class="icon-button conv-list-toggle" title="Conversations">${icon(I.list)}</button>
      <button class="icon-button conv-new" title="New conversation">${icon(I.plus)}</button>
      <button class="icon-button conv-close" title="Close (Esc)">${icon(I.chevron)}</button>
    </header>
    <aside class="agent-activity" hidden><header class="agent-activity-header"><h2>Agent activity</h2>
      <button class="icon-button activity-close" title="Close">×</button></header><div class="agent-activity-scroll"></div></aside>
    <div class="workspace-transcript"></div>
    <div class="workspace-composer">
      <div class="agent-settings-picker" role="dialog" aria-label="Agent settings" hidden></div>
      <form class="composer" data-agent-toolbar>
        <div class="composer-recipes" hidden></div>
        <div class="composer-selection" hidden><span></span><button type="button" class="icon-button drop-sel" title="Don't send the selection">×</button></div>
        <textarea rows="1" placeholder="Ask your agent to do anything..."></textarea>
        <div class="composer-footer">
          <button type="button" class="agent-settings-trigger" aria-label="Agent settings"></button>
          <button type="button" class="send-button composer-queue-action" title="Queue (Enter) — send after the current turn" hidden>${icon(I.clock, 15)}<span class="composer-send-label">Queue</span></button>
          <button type="submit" class="send-button" aria-label="Send message" disabled>${icon(I.up, 16)}</button>
        </div>
      </form>
    </div>
    </div>
  </section>
</div>`;
  const $ = (s) => root.querySelector(s);
  const wrap = $('.wrap'), barInput = $('.bar input'), transcript = $('.workspace-transcript'), textarea = $('textarea');
  const sendBtn = $('.send-button:not(.composer-queue-action)'), queueBtn = $('.composer-queue-action'), trigger = $('.agent-settings-trigger');
  const picker = $('.agent-settings-picker'), sidebar = $('.conv-sidebar'), convItems = $('.conv-items'), stopBtn = $('.stop-thread-button'), badge = $('.bar .badge');

  // ---------------------------------------------------------------- helpers

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
  // Markdown (CommonMark subset agents use). Links that point into Verticals (#goal/<id>,
  // #doc/<id>, /h/<date>) navigate the app in place; web links open outside; others stay text.
  function linkAttrs(url) {
    const u = String(url).trim();
    if (/^#(goal|doc)\/[^\s]+$/.test(u) || /^#(inbox|docs)$/.test(u) || /^\/h\/\d{4}-\d{2}-\d{2}\/?(#.*)?$/.test(u) || u === '/')
      return `href="${esc(u)}" data-app-link="${esc(u)}"`;
    const bare = /^(goal|doc)[:/]([\w-]+)$/.exec(u);
    if (bare) return `href="#${bare[1]}/${esc(bare[2])}" data-app-link="#${bare[1]}/${esc(bare[2])}"`;
    if (/^(https?:|mailto:)/i.test(u)) return `href="${esc(u)}" target="_blank" rel="noreferrer"`;
    return null;
  }
  function inline(src) {
    const slots = [];
    const keep = (html) => `\u0000${slots.push(html) - 1}\u0000`;
    let t = String(src)
      .replace(/`([^`]+)`/g, (_, c) => keep(`<code>${esc(c)}</code>`))
      .replace(/!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)/g, (_, alt, url) => keep(`<img alt="${esc(alt)}" src="${esc(url)}">`))
      .replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g, (m, text, url) => {
        const attrs = linkAttrs(url);
        return attrs ? keep(`<a ${attrs}>${inline(text)}</a>`) : keep(esc(text));
      })
      .replace(/<(https?:\/\/[^>\s]+)>/g, (_, url) => keep(`<a ${linkAttrs(url)}>${esc(url)}</a>`))
      .replace(/(^|[\s(])(https?:\/\/[^\s<)]+[^\s<).,;:!?'"])/g, (_, pre, url) => pre + keep(`<a ${linkAttrs(url)}>${esc(url)}</a>`));
    t = esc(t)
      .replace(/\*\*([^*]+)\*\*|__([^_]+)__/g, (_, a, b) => `<strong>${a ?? b}</strong>`)
      .replace(/(^|[^\w*])\*([^*\s][^*]*?)\*(?!\w)/g, '$1<em>$2</em>')
      .replace(/(^|[^\w_])_([^_\s][^_]*?)_(?!\w)/g, '$1<em>$2</em>')
      .replace(/~~([^~]+)~~/g, '<del>$1</del>');
    return t.replace(/\u0000(\d+)\u0000/g, (_, n) => slots[+n]);
  }
  function markdown(src) {
    const lines = String(src).replace(/\r/g, '').split('\n');
    const out = [];
    const isList = (l) => /^(\s*)([-*+•]|\d+[.)])\s+/.exec(l);
    const blockStart = (l) => /^(```|~~~|#{1,6}\s|>|\s*([-*+•]|\d+[.)])\s|\s*\|.*\|\s*$|\s*([-*_])(\s*\3){2,}\s*$)/.test(l);
    function list(i) {
      // Nested lists by indentation; "- [ ]" / "- [x]" render as task items.
      const base = isList(lines[i])[1].length, ordered = /\d/.test(isList(lines[i])[2]);
      const items = [];
      while (i < lines.length) {
        const m = isList(lines[i]);
        if (!m || m[1].length < base) break;
        if (m[1].length > base) { const [html, next] = list(i); items[items.length - 1] += html; i = next; continue; }
        if (/\d/.test(m[2]) !== ordered) break;
        let text = lines[i].slice(m[0].length);
        while (i + 1 < lines.length && lines[i + 1].trim() && !isList(lines[i + 1]) && !blockStart(lines[i + 1].trim()) && /^\s+/.test(lines[i + 1]))
          text += ' ' + lines[++i].trim();
        const task = /^\[([ xX])\]\s+/.exec(text);
        items.push(task ? `<input type="checkbox" disabled ${task[1] !== ' ' ? 'checked' : ''}> ${inline(text.slice(task[0].length))}` : inline(text));
        i++;
      }
      const tag = ordered ? 'ol' : 'ul';
      return [`<${tag}>${items.map((x) => `<li>${x}</li>`).join('')}</${tag}>`, i];
    }
    for (let i = 0; i < lines.length;) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      const fence = /^\s*(```|~~~)/.exec(line);
      if (fence) {
        const code = [];
        while (++i < lines.length && !lines[i].trim().startsWith(fence[1])) code.push(lines[i]);
        out.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);
        i++;
        continue;
      }
      const h = /^(#{1,6})\s+(.*)$/.exec(line);
      if (h) { const level = Math.min(6, h[1].length + 2); out.push(`<h${level}>${inline(h[2].replace(/\s+#+\s*$/, ''))}</h${level}>`); i++; continue; }
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { out.push('<hr>'); i++; continue; }
      if (/^\s*>/.test(line)) {
        const quote = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ''));
        out.push(`<blockquote>${markdown(quote.join('\n'))}</blockquote>`);
        continue;
      }
      if (/^\s*\|.*\|\s*$/.test(line)) {
        const rows = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++].trim().slice(1, -1).split('|').map((c) => c.trim()));
        const sep = rows[1] && rows[1].every((c) => /^:?-{2,}:?$/.test(c));
        const align = sep ? rows[1].map((c) => (c.startsWith(':') && c.endsWith(':') ? 'center' : c.endsWith(':') ? 'right' : '')) : [];
        const cell = (tag, c, k) => `<${tag}${align[k] ? ` style="text-align:${align[k]}"` : ''}>${inline(c)}</${tag}>`;
        const body = sep ? rows.slice(2) : rows.slice(1);
        out.push(`<table><thead><tr>${rows[0].map((c, k) => cell('th', c, k)).join('')}</tr></thead><tbody>${body.map((r) => `<tr>${r.map((c, k) => cell('td', c, k)).join('')}</tr>`).join('')}</tbody></table>`);
        continue;
      }
      if (isList(line)) { const [html, next] = list(i); out.push(html); i = next; continue; }
      const para = [line.trim()];
      while (i + 1 < lines.length && lines[i + 1].trim() && !blockStart(lines[i + 1])) para.push(lines[++i].trim());
      out.push(`<p>${para.map(inline).join('<br>')}</p>`);
      i++;
    }
    return out.join('');
  }
  // In-app links move Verticals the way its own navigation does (it listens to popstate).
  function openAppLink(url) {
    if (url.startsWith('#')) { location.hash = url; return; }
    history.pushState(history.state, '', url);
    dispatchEvent(new PopStateEvent('popstate', { state: history.state }));
  }
  const time = (ts) => new Date(ts || Date.now()).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  const agentOf = (id) => agents.find((a) => a.id === id) || { id, label: id === 'codex' ? 'Codex' : 'Claude Code', image: `${id}.svg`, efforts: [], permissions: [] };
  const asset = (name) => `/__chat/assets/${name}`;
  const clock = (ms) => { const s = Math.floor(ms / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
  const workedFor = (ms) => (ms < 60000 ? 'Worked for less than a minute' : `Worked for ${Math.round(ms / 60000)} minute${Math.round(ms / 60000) === 1 ? '' : 's'}`);
  const modelLabel = (provider, model) => {
    const m = (probes[provider]?.models || []).find((x) => x.value === model);
    return m ? m.label : model || '';
  };
  const effortLabel = (provider, effort) => agentOf(provider).efforts.find((e) => e.value === effort)?.label || '';

  async function api(path, body) {
    const res = await fetch(`/__chat/${path}`, body === undefined ? {} : { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  // ---------------------------------------------------------------- agent selection (Enjoy: last-model-selection)

  function defaultSelection(provider) {
    const a = agentOf(provider), saved = store.get('vt-chat:last-model-selection', {})[provider] || {};
    const prefs = store.get('vt-chat:agent-prefs', {})[provider] || {};
    return { provider, model: saved.model || '', effort: saved.reasoning || a.defaultEffort || 'medium',
             fast: !!prefs.fast, permission: prefs.permission || a.defaultPermission };
  }
  function saveSelection() {
    const all = store.get('vt-chat:last-model-selection', {});
    all[selection.provider] = { model: selection.model, reasoning: selection.effort };
    store.set('vt-chat:last-model-selection', all);
    const prefs = store.get('vt-chat:agent-prefs', {});
    prefs[selection.provider] = { fast: selection.fast, permission: selection.permission };
    store.set('vt-chat:agent-prefs', prefs);
    store.set('vt-chat:last-agent', selection.provider);
    const t = threads.find((x) => x.id === current);
    if (t) { t.selection = { ...selection }; saveThreads(); }
  }
  async function loadProbe(provider, force) {
    if (probes[provider] && !force && !probes[provider].error) return probes[provider];
    probes[provider] = { loading: true, models: probes[provider]?.models || [] };
    renderTrigger(); if (!picker.hidden) renderPicker();
    try { probes[provider] = await api(`probe?provider=${encodeURIComponent(provider)}`); }
    catch (e) { probes[provider] = { models: [], modelsError: 'Could not load models from this agent.', usage: { state: 'unavailable', message: e.message }, error: true }; }
    // Enjoy picks the first listed model when nothing was chosen before.
    if (selection.provider === provider && !selection.model && probes[provider].models?.length) {
      selection.model = probes[provider].models[0].value;
      saveSelection();
    }
    renderTrigger(); if (!picker.hidden) renderPicker();
    return probes[provider];
  }

  function renderTrigger() {
    const a = agentOf(selection.provider);
    const perm = a.permissions.find((p) => p.value === selection.permission);
    const showPerm = perm && selection.permission !== a.defaultPermission;
    const details = [modelLabel(selection.provider, selection.model) || (probes[selection.provider]?.loading ? '' : 'Choose model'),
                     effortLabel(selection.provider, selection.effort)].filter(Boolean).join(' ');
    trigger.title = [a.label, modelLabel(selection.provider, selection.model), effortLabel(selection.provider, selection.effort),
                     selection.fast ? 'Fast' : '', perm?.label].filter(Boolean).join(' · ');
    trigger.innerHTML = `<img alt="" src="${asset(a.image)}"><span class="agent-settings-summary"><span class="agent-settings-summary-top">
        <span class="agent-settings-summary-agent">${esc(a.label)}</span>
        ${showPerm ? `<span class="agent-settings-badge">${icon(I.lock, 10)}${esc(perm.label)}</span>` : ''}
        ${selection.fast ? `<span class="agent-settings-badge agent-settings-badge-fast">${icon(I.bolt, 10)}Fast</span>` : ''}
      </span><span class="agent-settings-summary-details">${esc(details)}</span></span>
      <span class="joy-select-chevron">${icon(I.chevron, 12)}</span>`;
    $('.bar-agent').src = asset(a.image);
  }

  let hoverDetail = null;
  function renderPicker() {
    const p = selection.provider, a = agentOf(p), probe = probes[p] || {};
    const choice = (label, pressed, attrs = '', extra = '', image = '') =>
      `<button type="button" class="agent-settings-choice" aria-pressed="${pressed}" ${attrs}>${image ? `<img alt="" src="${asset(image)}">` : ''}<span>${label}${extra}</span>${pressed ? `<span class="check">${icon(I.check, 11)}</span>` : ''}</button>`;
    // Agent column
    const agentCol = agents.map((x) => {
      const selected = x.id === p;
      let quota = '';
      if (selected) {
        const u = probe.usage;
        quota = `<div class="agent-settings-quota">${
          !u || probe.loading ? '<div class="agent-settings-quota-row"><span>Loading usage…</span></div>'
          : u.state !== 'ready' ? '<div class="agent-settings-quota-row"><span>Usage unavailable</span></div>'
          : u.windows.map((w) => `<div><div class="agent-settings-quota-row"><span>${esc(w.label)}</span><span>${w.remainingPercent}% left</span></div>
               <div class="agent-settings-quota-track"><i style="width:${w.remainingPercent}%"></i></div></div>`).join('')}</div>`;
      }
      return `<div class="agent-settings-agent">${choice(esc(x.label), selected, `data-agent="${x.id}" ${x.available ? '' : 'disabled'}`,
        x.available ? '' : '<small>Not installed</small>', x.image)}${quota}</div>`;
    }).join('');
    // Model column (a saved model the list lacks stays selectable, as in Enjoy)
    let models = probe.models || [];
    if (selection.model && !models.some((m) => m.value === selection.model))
      models = [{ value: selection.model, label: selection.model, detail: 'Your saved choice' }, ...models];
    const counts = {};
    models.forEach((m) => (counts[m.label] = (counts[m.label] || 0) + 1));
    const modelCol = probe.loading && !models.length ? choice('Loading models…', false, 'disabled')
      : !models.length ? choice('No models available', false, 'disabled')
      : models.map((m) => choice(esc(counts[m.label] > 1 ? `${m.label} (${m.value})` : m.label), m.value === selection.model,
          `data-model="${esc(m.value)}" data-detail="${esc(m.detail || '')}" ${probe.loading ? 'disabled' : ''}`, '', m.image || a.image)).join('');
    const status = probe.modelsError ? `<p class="agent-settings-status">${esc(probe.modelsError)}</p>` : '';
    const effortCol = a.efforts.map((e) => choice(esc(e.label), e.value === selection.effort, `data-effort="${e.value}"`)).join('');
    const speedCol = choice('Standard', !selection.fast, 'data-fast="0"') +
      choice('Fast', selection.fast, `data-fast="1" data-detail="${esc(a.fast || '')}"`);
    const permCol = a.permissions.map((x) => choice(esc(x.label), x.value === selection.permission,
      `data-permission="${x.value}" data-detail="${esc(x.detail)}"`)).join('');
    const perm = a.permissions.find((x) => x.value === selection.permission);
    picker.innerHTML = `<div class="agent-settings-scroll"><div class="agent-settings-columns">
        <section class="agent-settings-column"><h2>Agent</h2>${agentCol}</section>
        <section class="agent-settings-column"><h2>Model</h2>${modelCol}${status}</section>
        <section class="agent-settings-column"><h2>Effort</h2>${effortCol}</section>
        <section class="agent-settings-column"><h2>Speed</h2>${speedCol}</section>
        <section class="agent-settings-column"><h2>Permissions</h2>${permCol}</section>
      </div></div>
      <div class="agent-settings-footer"><p>${esc(hoverDetail || perm?.detail || 'Applies to your next message.')}</p>
        <label class="agent-settings-close-after-selection"><input type="checkbox" ${store.get('vt-chat:close-after-selection', false) ? 'checked' : ''}> Close after selection</label></div>`;
    picker.querySelectorAll('.agent-settings-choice:not(:disabled)').forEach((b) => {
      b.onmouseenter = b.onfocus = () => { if (b.dataset.detail !== undefined) { hoverDetail = b.dataset.detail || null; picker.querySelector('.agent-settings-footer p').textContent = hoverDetail || perm?.detail || 'Applies to your next message.'; } };
      b.onclick = () => choose(b.dataset);
    });
    picker.querySelector('.agent-settings-close-after-selection input').onchange = (e) => store.set('vt-chat:close-after-selection', e.target.checked);
  }
  function choose(d) {
    if (d.agent && d.agent !== selection.provider) {
      // Enjoy's changeAgent: the new agent's remembered model and effort, its default permission, no Fast.
      selection = { ...defaultSelection(d.agent), fast: false, permission: agentOf(d.agent).defaultPermission };
      loadProbe(d.agent);
    }
    if (d.model !== undefined) selection.model = d.model;
    if (d.effort) selection.effort = d.effort;
    if (d.fast !== undefined) selection.fast = d.fast === '1';
    if (d.permission) selection.permission = d.permission;
    saveSelection();
    renderTrigger();
    if (store.get('vt-chat:close-after-selection', false)) closePicker(); else renderPicker();
  }
  function openPicker() {
    hoverDetail = null;
    picker.hidden = false;
    trigger.dataset.state = 'open';
    renderPicker();
    loadProbe(selection.provider, true);
    api('agents').then((r) => { agents = r.agents; renderPicker(); }).catch(() => {});
  }
  function closePicker() { picker.hidden = true; delete trigger.dataset.state; }

  // ---------------------------------------------------------------- conversations

  function saveThreads() { store.set('vt-chat:threads', threads.slice(0, 100)); }
  function touchThread(patch) {
    let t = threads.find((x) => x.id === current);
    if (!t) { t = { id: current, title: '', provider: selection.provider, updatedAt: Date.now(), status: 'idle' }; threads.unshift(t); }
    Object.assign(t, patch, { updatedAt: Date.now() });
    threads = [t, ...threads.filter((x) => x !== t)];
    saveThreads();
    renderHeader();
    renderList();
  }
  function renderHeader() {
    const t = threads.find((x) => x.id === current);
    $('.conv-title h1').textContent = t?.title || 'New conversation';
    const status = t?.status === 'needs-you' ? 'Needs you' : running ? 'Working' : t?.status === 'failed' ? 'Failed' : t ? 'Ready' : '';
    $('.conv-status').textContent = status;
    stopBtn.hidden = !running;
  }
  let filter = 'all';
  const statusOf = (t) => (t.id === current && running ? 'working' : t.status || 'idle');
  function renderList() {
    if (sidebar.hidden) return;
    const date = (ts) => new Date(ts).toLocaleDateString([], { month: 'short', day: 'numeric' });
    const count = (f) => threads.filter((t) => f === 'all' || statusOf(t) === f).length;
    sidebar.querySelector('.conversation-filters').innerHTML = [['all', 'All'], ['needs-you', 'Needs you'], ['working', 'Working']]
      .map(([f, label]) => `<button data-filter="${f}" aria-pressed="${filter === f}">${label}<small>${count(f)}</small></button>`).join('');
    sidebar.querySelectorAll('.conversation-filters button').forEach((b) => (b.onclick = () => { filter = b.dataset.filter; renderList(); }));
    const shown = threads.filter((t) => filter === 'all' || statusOf(t) === filter);
    convItems.innerHTML = shown.length ? shown.map((t) => {
      const st = statusOf(t);
      const badgeHtml = st === 'working' ? '<span class="conversation-badge is-running"><span class="working-spinner"><i></i><i></i><i></i></span>Working</span>'
        : st === 'needs-you' ? '<span class="conversation-badge is-blocked">Needs you</span>'
        : st === 'failed' ? `<span class="conversation-badge is-failed">${icon(I.alert, 11)}Failed</span>` : '';
      return `<button class="conv-item" data-id="${t.id}" aria-current="${t.id === current}">
        ${t.goal ? `<span class="thread-label">${esc(t.goal.title)}</span>` : ''}<strong>${esc(t.title || 'New conversation')}</strong>
        <span class="meta"><span>${esc(agentOf(t.provider).label)} · ${date(t.updatedAt)}</span>${badgeHtml}</span></button>`;
    }).join('') : '<div class="conv-empty">No conversations yet</div>';
    convItems.querySelectorAll('.conv-item').forEach((b) => (b.onclick = () => openThread(b.dataset.id)));
  }
  function setSidebar(open) {
    sidebar.hidden = !open;
    wrap.classList.toggle('with-sidebar', open);
    store.set('vt-chat:sidebar', open);
    $('.conv-list-toggle').setAttribute('aria-pressed', String(open));
    renderList();
  }
  function renderRecipes() {
    const t = threads.find((x) => x.id === current);
    const box = $('.composer-recipes');
    const goal = t?.goal || pendingGoal;
    box.hidden = !goal;
    box.innerHTML = goal ? `<span class="composer-chip" title="This conversation is about this goal">${icon(I.target, 12)}<span>${esc(goal.title)}</span><small>goal</small></span>` : '';
  }
  function openThread(id, goal = null) {
    pendingGoal = goal;
    current = id;
    store.set('vt-chat:current', id);
    history = store.get(`vt-chat:events:${id}`, []);
    cursor = store.get(`vt-chat:cursor:${id}`, { boot: null, seq: 0 });
    const t = threads.find((x) => x.id === id);
    selection = t?.selection ? { ...t.selection } : defaultSelection(store.get('vt-chat:last-agent', 'claude'));
    if (!agents.some((a) => a.id === selection.provider && a.available) && agents.length) selection = defaultSelection('claude');
    resetView();
    history.forEach((ev) => render(ev, false));
    if (!history.length) renderEmpty();
    setRunning(false);
    renderTrigger();
    renderHeader();
    renderRecipes();
    renderList();
    loadProbe(selection.provider);
    connect();
  }
  function newThread(goal = null) {
    openThread(uuid(), goal);
    textarea.focus();
  }
  // "Discuss" on a goal card: a new conversation that carries a reference to that goal.
  function openGoalChat(goal) {
    expand();
    newThread(goal);
    $('.conv-title h1').textContent = goal.title;
  }

  // ---------------------------------------------------------------- transcript

  let turn = null;          // the incoming message being built: {el, bubble, raw, activity, tools, started, ...}
  const tools = new Map();
  let ticker = null;
  const activityScroll = $('.agent-activity-scroll'), activityPane = $('.agent-activity'), activityToggle = $('.workspace-activity-toggle');
  function resetView() {
    transcript.innerHTML = ''; turn = null; tools.clear();
    activityScroll.innerHTML = '<div class="activity-empty">Tool calls and commands from this conversation appear here.</div>';
  }
  function activityGroup(t) {
    if (!t.activity) {
      activityScroll.querySelector('.activity-empty')?.remove();
      const head = document.createElement('div');
      head.className = 'activity-session-heading';
      head.innerHTML = `<span>${esc(agentOf(t.provider || selection.provider).label)}</span><time>${time(t.started)}</time>`;
      const group = document.createElement('div');
      group.style.cssText = 'display:flex;flex-direction:column;gap:8px';
      activityScroll.append(head, group);
      t.activity = group;
    }
    return t.activity;
  }
  function toggleActivity(open) {
    activityPane.hidden = open === undefined ? !activityPane.hidden : !open;
    activityToggle.setAttribute('aria-expanded', String(!activityPane.hidden));
    if (!activityPane.hidden) activityScroll.scrollTop = activityScroll.scrollHeight;
  }
  function renderEmpty() {
    transcript.innerHTML = `<div class="empty"><b>What are you working on?</b>The agent sees the screen you have open and works on your board through Verticals.</div>`;
  }
  const scroll = () => { transcript.scrollTop = transcript.scrollHeight; };
  function add(el) { transcript.querySelector('.empty')?.remove(); transcript.appendChild(el); scroll(); return el; }

  function startTurn(ev, ts) {
    const a = agentOf(ev.provider || selection.provider);
    const el = document.createElement('article');
    el.className = 'message incoming';
    el.innerHTML = `<div class="message-body"><div class="message-meta has-agent-avatar"><img class="message-agent-avatar" alt="" src="${asset(a.image)}">
        <strong>${esc(a.label)}</strong><time>${time(ts)}</time><span class="message-work-time"></span>
        <span class="message-model-info"></span></div>
      <button type="button" class="message-working-indicator" hidden><span class="conversation-badge is-running">
        <span class="working-spinner"><i></i><i></i><i></i></span><span>Working</span><span class="working-timer">0:00</span>
        <span class="working-activity">Starting…</span>${icon(I.chevron, 12)}</span></button></div>`;
    add(el);
    turn = { el, bubble: null, raw: '', started: ts || Date.now(), provider: ev.provider, model: ev.model, effort: ev.effort,
             indicator: el.querySelector('.message-working-indicator'), activity: null };
    turn.indicator.onclick = () => toggleActivity(true);
    const info = [modelLabel(ev.provider, ev.model), effortLabel(ev.provider, ev.effort) && `${effortLabel(ev.provider, ev.effort)} effort`].filter(Boolean);
    el.querySelector('.message-model-info').innerHTML = info.map((x) => `<span>${esc(x)}</span>`).join('');
    return turn;
  }
  function ensureTurn(ts) { return turn || startTurn({ provider: selection.provider }, ts); }

  function render(ev, live) {
    const ts = ev.ts;
    switch (ev.t) {
      case 'user': {
        turn = null;
        const el = document.createElement('article');
        el.className = 'message outgoing';
        el.innerHTML = `<div class="message-body"><div class="message-meta"><span class="message-user-avatar">${icon(I.user, 22, 'stroke-width="1.3"')}</span>
          <strong>You</strong><time>${time(ts)}</time></div><div class="message-bubble"><div class="message-markdown"></div></div></div>`;
        el.querySelector('.message-markdown').textContent = ev.text;
        add(el);
        break;
      }
      case 'turn_start': {
        // Reuse a card opened by an early activity event; otherwise start the agent's message.
        if (turn && !turn.bubble && !turn.el.querySelector('.decision')) turn.el.remove();
        startTurn(ev, ts);
        if (live) setRunning(true);
        break;
      }
      case 'activity': {
        const t = ensureTurn(ts);
        t.indicator.hidden = false;
        t.indicator.querySelector('.working-activity').textContent = ev.label;
        if (live) setRunning(true);
        break;
      }
      case 'text_start': if (turn) turn.textBreak = !!turn.raw; break;
      case 'text': {
        const t = ensureTurn(ts);
        if (!t.bubble) {
          t.bubble = document.createElement('div');
          t.bubble.className = 'message-bubble';
          t.bubble.innerHTML = '<div class="bubble-text message-markdown"></div>';
          t.el.querySelector('.message-body').appendChild(t.bubble);
        }
        if (t.textBreak) { t.raw += '\n\n'; t.textBreak = false; }
        t.raw += ev.text;
        t.bubble.firstChild.innerHTML = markdown(t.raw);
        scroll();
        break;
      }
      case 'tool': {
        const t = ensureTurn(ts);
        const el = document.createElement('details');
        el.className = 'tool-activity is-running';
        el.innerHTML = `<summary><span class="tool-activity-icon">${icon(I.tool, 15)}</span><span class="tool-activity-label"><span>Running</span>
          <strong>${esc(ev.title || ev.name)}</strong></span><span class="tool-activity-state">${icon(I.chevron, 13)}</span></summary>
          <div class="tool-activity-body"><pre>${esc(JSON.stringify(ev.input, null, 2))}</pre></div>`;
        tools.set(ev.id, el);
        activityGroup(t).appendChild(el);
        t.indicator.hidden = false;
        break;
      }
      case 'tool_result': {
        const el = tools.get(ev.id);
        if (!el) break;
        el.classList.remove('is-running');
        el.classList.toggle('is-failed', !!ev.error);
        el.querySelector('.tool-activity-label > span').textContent = ev.error ? 'Failed' : 'Done';
        if (ev.summary) el.querySelector('pre').textContent += `\n\n${ev.summary}`;
        break;
      }
      case 'permission': {
        const t = ensureTurn(ts);
        const el = document.createElement('div');
        el.className = 'decision';
        el.dataset.id = ev.requestId;
        el.innerHTML = `<h3>${esc(ev.title)}</h3>${ev.body ? `<pre>${esc(ev.body)}</pre>` : ''}
          <div class="decision-options">${ev.options.map((o) => `<button type="button" class="decision-option" data-value="${esc(o.value)}"><i></i><strong>${esc(o.label)}</strong></button>`).join('')}</div>`;
        el.querySelectorAll('.decision-option').forEach((b) => (b.onclick = () => decide(ev.requestId, b.dataset.value, el)));
        t.el.querySelector('.message-body').insertBefore(el, t.bubble || null);
        scroll();
        if (live) { touchThread({ status: 'needs-you' }); if (!expanded) badge.hidden = false; }
        break;
      }
      case 'permission_done': {
        const el = transcript.querySelector(`.decision[data-id="${CSS.escape(String(ev.requestId))}"]`);
        if (el) {
          el.classList.add('resolved');
          el.querySelectorAll('.decision-option').forEach((b) => { b.disabled = true; if (ev.value !== undefined && b.dataset.value === String(ev.value)) b.classList.add('selected'); });
        }
        if (live && running) touchThread({ status: 'working' });
        break;
      }
      case 'done': {
        const t = turn;
        if (t) {
          t.indicator.hidden = true;
          t.el.querySelector('.message-work-time').textContent = workedFor(ev.ms || 0);
        }
        if (ev.error && ev.detail) add(Object.assign(document.createElement('p'), { className: 'system-message error', textContent: ev.detail }));
        turn = null;
        if (live) { setRunning(false); touchThread({ status: ev.error ? 'failed' : 'idle' }); }
        break;
      }
      case 'exit':
        if (ev.code) add(Object.assign(document.createElement('p'), { className: 'system-message error', textContent: `The agent stopped (exit ${ev.code}). ${ev.detail || ''}` }));
        if (turn) turn.indicator.hidden = true;
        turn = null;
        if (live) { setRunning(false); touchThread({ status: 'failed' }); }
        break;
      case 'local_error':
        add(Object.assign(document.createElement('p'), { className: 'system-message error', textContent: ev.text }));
        break;
    }
  }

  function setRunning(value) {
    running = value;
    stopBtn.hidden = !value;
    updateSend();
    clearInterval(ticker);
    if (value) ticker = setInterval(() => {
      if (turn) turn.indicator.querySelector('.working-timer') && (turn.indicator.querySelector('.working-timer').textContent = clock(Date.now() - turn.started));
    }, 1000);
    renderHeader();
  }
  function updateSend() {
    const has = !!textarea.value.trim();
    sendBtn.disabled = !has;
    queueBtn.hidden = !(running && has);
    sendBtn.title = running && has ? 'Send (Cmd/Ctrl+Enter) — send immediately' : 'Send message';
  }
  function record(ev, live = true) {
    ev.ts = ev.ts || Date.now();
    history.push(ev);
    if (history.length > 1500) history = history.slice(-1500);
    store.set(`vt-chat:events:${current}`, history);
    render(ev, live);
  }

  // ---------------------------------------------------------------- server

  function connect() {
    if (stream) stream.close();
    const session = current;
    stream = new EventSource(`/__chat/events?session=${encodeURIComponent(session)}&since=${cursor.seq}&boot=${encodeURIComponent(cursor.boot || '')}`);
    stream.addEventListener('hello', (m) => {
      const { boot } = JSON.parse(m.data);
      if (cursor.boot !== boot) { cursor = { boot, seq: 0 }; store.set(`vt-chat:cursor:${session}`, cursor); if (running) setRunning(false); }
    });
    stream.onmessage = (m) => {
      if (session !== current) return;
      const { seq, event } = JSON.parse(m.data);
      if (seq <= cursor.seq) return;
      cursor.seq = seq;
      store.set(`vt-chat:cursor:${session}`, cursor);
      const last = history[history.length - 1];
      if (event.t === 'user' && last && last.t === 'user' && last.pending && last.text === event.text) { last.pending = false; return; }
      record(event);
    };
  }
  async function submit(mode) {
    const text = textarea.value.trim();
    if (!text) return;
    closePicker();
    expand();
    textarea.value = '';
    autosize();
    updateSend();
    const context = {
      today: new Date().toLocaleDateString('sv-SE'), tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
      url: location.pathname + location.search + location.hash, title: document.title,
      heading: (document.querySelector('[role="dialog"] h1, [role="dialog"] h2, main h1, h1')?.innerText || '').slice(0, 200),
      selection: lastSelection,
      goal: (threads.find((t) => t.id === current)?.goal) || pendingGoal || undefined,
    };
    clearSelection();
    if (!threads.some((t) => t.id === current)) {
      touchThread({ title: pendingGoal ? pendingGoal.title : text.slice(0, 80), provider: selection.provider, goal: pendingGoal || undefined });
      pendingGoal = null;
    }
    touchThread({ provider: selection.provider, status: 'working' });
    record({ t: 'user', text, pending: true });
    try {
      await api('send', { session: current, text, context, settings: selection, mode });
    } catch (e) {
      record({ t: 'local_error', text: e.message });
      touchThread({ status: running ? 'working' : 'idle' });
    }
  }
  async function decide(requestId, value, el) {
    el.querySelectorAll('.decision-option').forEach((b) => (b.disabled = true));
    badge.hidden = true;
    try { await api('permission', { session: current, requestId, value }); }
    catch (e) { el.querySelectorAll('.decision-option').forEach((b) => (b.disabled = false)); record({ t: 'local_error', text: e.message }); }
  }

  // ---------------------------------------------------------------- behaviour

  function expand() {
    if (expanded) return;
    expanded = true;
    wrap.classList.add('open');
    badge.hidden = true;
    if (barInput.value) { textarea.value = barInput.value; barInput.value = ''; }
    autosize(); updateSend(); scroll();
    setTimeout(() => textarea.focus(), 0);
  }
  function collapse() { expanded = false; wrap.classList.remove('open'); closePicker(); }
  function autosize() { textarea.style.height = 'auto'; textarea.style.height = `${Math.min(180, textarea.scrollHeight)}px`; }
  function clearSelection() { lastSelection = ''; $('.composer-selection').hidden = true; }

  barInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && barInput.value.trim()) { e.preventDefault(); expand(); submit('send'); }
    if (e.key === 'Escape') barInput.blur();
  });
  barInput.addEventListener('focus', () => { if (history.length) expand(); });
  $('.bar').addEventListener('mousedown', (e) => { if (e.target !== barInput) { e.preventDefault(); barInput.focus(); } });
  textarea.addEventListener('input', () => { autosize(); updateSend(); });
  textarea.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      // Enjoy: while the agent works, Enter queues and Cmd/Ctrl+Enter sends immediately.
      submit(running && !(e.metaKey || e.ctrlKey) ? 'queue' : running ? 'now' : 'send');
    }
    if (e.key === 'Escape') { e.preventDefault(); if (!picker.hidden) closePicker(); else collapse(); }
  });
  $('form').onsubmit = (e) => { e.preventDefault(); submit(running ? 'now' : 'send'); };
  queueBtn.onclick = () => submit('queue');
  stopBtn.onclick = () => api('stop', { session: current }).catch(() => {});
  trigger.onclick = () => (picker.hidden ? openPicker() : closePicker());
  trigger.onkeydown = (e) => { if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { e.preventDefault(); openPicker(); } };
  $('.conv-close').onclick = collapse;
  activityToggle.onclick = () => toggleActivity();
  $('.activity-close').onclick = () => toggleActivity(false);
  $('.conv-new').onclick = () => newThread();
  $('.conv-list-toggle').onclick = () => setSidebar(sidebar.hidden);
  $('.conv-new-round').onclick = () => newThread();
  // In-app links (goals, docs, board dates) navigate Verticals instead of leaving the page.
  transcript.addEventListener('click', (e) => {
    const a = e.target.closest?.('a[data-app-link]');
    if (!a) return;
    e.preventDefault();
    openAppLink(a.dataset.appLink);
  });
  $('.drop-sel').onclick = clearSelection;
  root.addEventListener('mousedown', (e) => {
    const path = e.composedPath();
    if (!picker.hidden && !path.includes(picker) && !path.includes(trigger)) closePicker();
  });

  // The page selection is context: remember it before focus moves into the chat.
  document.addEventListener('selectionchange', () => {
    const sel = document.getSelection(), text = String(sel || '').trim();
    if (!text || host.contains(sel.anchorNode)) return;
    lastSelection = text.slice(0, 2000);
    $('.composer-selection').hidden = false;
    $('.composer-selection span').textContent = `Selection: “${lastSelection.slice(0, 120)}”`;
  });
  document.addEventListener('mousedown', (e) => { if (!e.composedPath().includes(host)) clearSelection(); }, true);
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      if (expanded) collapse(); else if (history.length) expand(); else barInput.focus();
    }
  }, true);

  // ---------------------------------------------------------------- start

  // Goal cards are Verticals' own DOM (.goal-card[data-goal-id] > .goal-card__row). The button sits
  // next to the card's "…" menu, appears on hover like it, and never starts the row's drag.
  const goalStyle = document.createElement('style');
  goalStyle.textContent = `
    .goal-card > .goal-card__row > .vt-goal-chat { position:absolute; z-index:2; top:-1px; right:26px; width:24px; height:24px; padding:0;
      display:grid; place-items:center; border:0; border-radius:50%; background:transparent; color:currentColor; cursor:pointer; opacity:0;
      transition:opacity .15s cubic-bezier(.165,.84,.44,1); }
    .goal-card:hover > .goal-card__row > .vt-goal-chat, .vt-goal-chat:focus-visible { opacity:.55; }
    .goal-card > .goal-card__row > .vt-goal-chat:hover { opacity:1; background:rgba(0,0,0,.06); }
    .vt-goal-chat svg { width:14px; height:14px; }`;
  function addGoalButtons(scope = document) {
    scope.querySelectorAll?.('.goal-card[data-goal-id] > .goal-card__row').forEach((row) => {
      if (row.querySelector(':scope > .vt-goal-chat')) return;
      const card = row.parentElement;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'vt-goal-chat';
      btn.title = 'Discuss with your agent';
      btn.setAttribute('aria-label', 'Discuss this goal with your agent');
      btn.innerHTML = icon(I.message, 14);
      for (const type of ['pointerdown', 'mousedown', 'touchstart', 'dblclick', 'contextmenu', 'keydown'])
        btn.addEventListener(type, (e) => e.stopPropagation());
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const title = (card.querySelector('.goal-card__title-text')?.innerText || '').replace(/^Due\.\s*/, '').trim();
        openGoalChat({ id: card.dataset.goalId, title: title || 'Goal' });
      });
      row.appendChild(btn);
    });
  }
  new MutationObserver((records) => {
    for (const r of records) for (const n of r.addedNodes) if (n.nodeType === 1) addGoalButtons(n.parentElement || n);
  }).observe(document.documentElement, { childList: true, subtree: true });

  async function mount() {
    document.head.appendChild(goalStyle);
    addGoalButtons();
    document.body.appendChild(host);
    try { agents = (await api('agents')).agents; } catch {}
    openThread(current || uuid());
    setSidebar(store.get('vt-chat:sidebar', false));
  }
  if (document.body) mount(); else document.addEventListener('DOMContentLoaded', mount);
})();
