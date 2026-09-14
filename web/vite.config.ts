// Verticals frontend build. Vue 3 SFCs consuming the private kit
// (@konstantinopolskii/design-system + @konstantinopolskii/vue, vendored — see web/vendor/) and
// nothing else: no router, no state library, no CSS framework. docs/BRIEF.md rule 8.
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// WP-22: same-origin proxy for `/api/*` (and `/healthz`). `verticals/api/app.py` serves no static
// files and adds no CORSMiddleware on purpose (S-114) — the shipped topology is a real static
// server in front of `dist/` plus a real uvicorn subprocess, with nothing joining the two into one
// origin unless something here does it. `npm run dev` needs this for local development against a
// real backend; the `ui` test suite needs the identical config under `vite preview`
// (`docs/E2E.md` §6: "serves dist/ with a real static server" — `preview.proxy` is what makes
// that server also same-origin with the backend, without touching `verticals/api/app.py` at all).
// Target is an env var, not hardcoded: `tests/ui/conftest.py` starts uvicorn on a fresh ephemeral
// port per test run (same pattern as `tests/http/conftest.py::_free_port`) and points this at it.
export default defineConfig(({ mode }) => {
  // `tsconfig.json`'s `types` is scoped to `["vite/client"]` only (no `"node"`) — deliberately,
  // for a browser app that has exactly one Node-side line. Adding `@types/node` as a
  // devDependency for this alone would be a dependency for one global; a narrow cast reads it
  // instead. `globalThis.process` genuinely exists at runtime here — this file only ever runs
  // under Vite's own Node-hosted config loader, never bundled for the browser.
  const cwd = (globalThis as { process?: { cwd(): string } }).process?.cwd() ?? '.'
  const env = loadEnv(mode, cwd, '')
  const target = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'
  const proxy = {
    '/api': { target, changeOrigin: true },
    '/healthz': { target, changeOrigin: true },
  }
  return {
    plugins: [vue()],
    build: {
      // Keep the artifact deterministic and easy to serve statically (nginx, WP-29).
      outDir: 'dist',
      assetsDir: 'assets',
    },
    server: { proxy },
    preview: { proxy },
  }
})
