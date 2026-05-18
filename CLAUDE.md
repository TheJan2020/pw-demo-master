# PW Demo Master — Claude project context

You're working on **PW Demo Master**, a FastAPI + vanilla-JS SPA that demos four
integrations together: **Frigate** (NVR), **Home Assistant**, **Gemini Live**
(voice agent), and an **AI-Camera Playground** (vision rules over Frigate
cameras), tied together by an **MQTT** subscription so motion state is push,
not polled. The README has the user-facing setup. This file is the orientation
brief for *you*.

## Hard-won architectural decisions — don't relitigate

- **Single FastAPI process serves both API and frontend.** No bundler, no
  build step. The frontend is plain HTML/CSS/JS under `frontend/`. The HTML
  uses hash-based routing; navigation is intercepted in `frontend/app.js`'s
  `navigate()`.
- **State and credentials live in `data/state.json`** via `backend/app/core/state.py`.
  That file is gitignored — re-enter creds per machine via Settings.
- **One Gemini model setting in Settings drives both** the Live Agent (uses
  the model verbatim, e.g. `gemini-3.1-flash-live-preview`) and the AI-Camera
  Playground (`_resolve_vision_model` calls Gemini ListModels and picks a
  non-Live counterpart that the account actually has access to — `-live*`
  suffix stripping with a fallback chain of `gemini-2.5-flash` → `2.0-flash`
  → `1.5-flash`).
- **Don't switch the Playground back to the Gemini Live API.** Live returned
  1011 (text-only modality not supported on `*-live*` models). Playground
  uses `client.aio.models.generate_content` with `response_schema` so the
  JSON verdict is enforced server-side. The "session" requirement is honored
  by giving each playground WS its own `genai.Client` instance.
- **MQTT is the source of truth for motion.** `backend/app/services/mqtt.py`
  is a singleton. It subscribes to `<prefix>/+/motion` and `<prefix>/events`,
  caches per-camera state, and broadcasts to WS subscribers. The Playground
  WS `/api/frigate/motion/ws` is push-based — no polling. There's a legacy
  HTTP `/api/frigate/motion` endpoint that still works as a fallback.
- **Home Assistant control knowledge is centralised** in
  `backend/app/knowledge/homeassistant.py`. The Smart Home → Test page,
  Smart Home → Main area dashboard, and the Live Agent's system instruction
  all read from it. Update there once and everything follows.
- **AI-Camera Playground's "Periodic + Motion" semantics are AND, not OR.**
  Motion gates the countdown. First scan fires the moment motion first turns
  ON; subsequent scans fire when accumulated motion-active time reaches
  `period_s`. When motion stops, the countdown freezes; when motion resumes,
  it continues from where it paused. The countdown is computed inside
  `_RunContext` in `backend/app/routers/ai_camera.py` and emitted every
  second over the WS as `{type:"countdown", remaining_s, paused, waiting_for_motion}`.
- **Triggered iterations fire a red strobe + Web Audio siren in the browser**,
  silenced by a banner button. The `AudioContext` is primed inside the user
  gesture (`primeAlarmAudio()` in `Start Session`) so the browser allows
  playback when an iteration later triggers.
- **WebSocket message envelopes are tiny JSON dicts with a `type` field.**
  Keep new event types additive; the frontend `handlePgMessage` / Live Agent
  `handleServerMessage` switch on `type`. Don't repurpose existing types.
- **System Python diagnostics are false positives.** The IDE may complain
  "Cannot find module 'httpx'/'fastapi'/'google'/'aiomqtt'" because it inspects
  the system Python interpreter. The runtime uses `.venv/bin/python` (macOS)
  or `.venv\Scripts\python.exe` (Windows), which has all deps. Ignore the
  "module not found" hints unless you actually changed `requirements.txt`.

## Code map

| Area | Path |
| --- | --- |
| FastAPI entrypoint, lifespan, static mount | `backend/app/main.py` |
| Settings persistence | `backend/app/core/state.py` |
| MQTT singleton (subscribes, broadcasts) | `backend/app/services/mqtt.py` |
| HA capabilities catalog (single source of truth) | `backend/app/knowledge/homeassistant.py` |
| Frigate router (cameras, events, motion WS) | `backend/app/routers/frigate.py` |
| Home Assistant router | `backend/app/routers/homeassistant.py` |
| Live Agent (Gemini Live + HA tool calls) | `backend/app/routers/live_agent.py` |
| AI-Camera Playground (vision rule runner) | `backend/app/routers/ai_camera.py` |
| MQTT broker config + health | `backend/app/routers/mqtt.py` |
| SPA shell + routes + page renderers | `frontend/app.js` |
| Live Agent client (mic, audio playback, WS, STT) | `frontend/live-agent.js` |
| All styles | `frontend/styles.css` |

## Frontend page → route map

| Sidebar | Hash route | Renderer in `app.js` |
| --- | --- | --- |
| Home | `#/home` | `renderHome` |
| Frigate · Home | `#/frigate/home` | `renderFrigateHome` |
| Frigate · Events | `#/frigate/events` | `renderFrigateEvents` |
| Smart Home · Main | `#/smart-home/main` | `renderSmartHomeMain` |
| Smart Home · Test | `#/smart-home/test` | `renderSmartHomeTest` |
| Smart Home · Live Agent | `#/smart-home/live-agent` | `renderLiveAgent` |
| AI-Camera · Main | `#/ai-camera/main` | `renderAiCameraMain` (stub) |
| AI-Camera · Rules | `#/ai-camera/rules` | `renderAiCameraRules` (stub) |
| AI-Camera · Playground | `#/ai-camera/playground` | `renderAiCameraPlayground` |
| Settings | `#/settings` | `renderSettings` |

## Style / behavioural conventions

- **Two false-positive IDE error classes to ignore**: (a) "Cannot find module"
  for `fastapi`/`httpx`/`google.genai`/`aiomqtt`/`pydantic` — see above.
  (b) "Unused import" hints that resolve as soon as the next edit lands.
  Real parse errors and runtime errors are not in that category — fix them.
- **Reuse the existing modal**: defined in `frontend/index.html` and driven
  by `showModal({title, sub, openUrl, bodyHtml, onClose})` /  `closeModal()`
  in `frontend/live-agent.js`. Used by Live Agent, Frigate event playback,
  and AI-Camera thumbnail enlargement. Don't roll a new modal.
- **Topbar status pills** (Frigate / HA / MQTT) are polled by
  `refreshHealth()` every 15s and use a shared `setPillStatus(prefix, …)`.
- **Two persistent client-side stores**: `localStorage["pwdemo.prefs"]` for
  theme + sidebar collapsed state; `localStorage["pwdemo.settings"]` is
  legacy (settings now live on the backend).
- **The Smart Home Test page** generates control widgets from the knowledge
  catalog with **opt-in checkboxes per parameter** — required because HA
  rejects calls that mix mutually exclusive light parameters
  (`brightness` vs `brightness_pct` vs `rgb_color` etc).
- **Half-duplex on Live Agent**: while the agent is speaking, browser STT
  is gated and the recognizer is aborted to discard any echoed input. The
  gate lifts ~250ms after the audio queue drains. See
  `frontend/live-agent.js` `beginEcho` / `scheduleEchoEnd`.

## When in doubt

- The README is for the user. CLAUDE.md (this file) is for you.
- `data/state.json` is gitignored — never tell the user to commit it.
- `data/demos/*/persona.txt`, `data/demos/*/kb.txt`, and
  `data/demos/*/whatsapp_templates.json` ARE tracked by git (they're
  content the SPA's editor pages write — not secrets, and we want
  them in sync across machines). Everything else under `data/demos/`
  stays per-machine: `calls/`, `snapshot.json`, `whatsapp_inbox.json`,
  `escalation.json` (which holds the AMI password + Wasender API
  key). See `.gitignore` for the exact carve-out.
- Don't run destructive git commands (`reset --hard`, `push --force`, etc.)
  without explicit user authorization for that specific action.
- Don't introduce a build step. The frontend deliberately ships as static
  files served by FastAPI's StaticFiles mount.
