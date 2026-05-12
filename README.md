# PW Demo Master

A single-port FastAPI app that wires four integrations into one demo dashboard:

- **Frigate** — NVR with object detection. Lists cameras, browses snapshots and event clips, exposes a per-camera motion endpoint.
- **Home Assistant** — Area dashboard, smart Test page with attribute-aware controls, and tool calls for the Live Agent.
- **Gemini Live Agent** — Real-time voice + vision conversation that can drive Home Assistant.
- **AI-Camera Playground** — Vision rule runner (e.g. "trigger if you see anyone without a hi-vis vest"), driven by a dedicated Gemini session, gated by Frigate motion.
- **MQTT** — Subscribes to the broker Frigate publishes to, so motion state is push-based instead of polled.

The backend is FastAPI + httpx + aiomqtt + google-genai. The frontend is a single SPA (`frontend/`) — hash-routed, no build step.

## Requirements

- Python 3.10+ (3.9 also works but is past upstream EOL — Google's auth libs warn)
- A modern browser (Chrome / Edge / Safari)
- (Optional) Frigate, Home Assistant, MQTT broker, Gemini API key — each is independent; the parts of the app that don't have their dependency configured show a clear "configure in Settings" hint.

## Running

### macOS / Linux

```bash
./run.sh
```

### Windows

PowerShell (preferred):

```powershell
.\run.ps1
```

The first time you may need to allow the script:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

Or use `cmd.exe`:

```cmd
run.bat
```

Both runners create a `.venv` on first run, install `backend/requirements.txt`, and start `uvicorn` on port 8080 with `--reload`. Override the port with the `PORT` env var.

Open <http://localhost:8080> and head to **Settings** to configure each integration.

## Configuration

All credentials live in `data/state.json`, which is **gitignored**. After cloning fresh on a new machine you'll re-enter:

- **Frigate URL** (e.g. `http://192.168.1.50:5000`)
- **Home Assistant URL** + **Long-Lived Access Token**
- **Gemini API key** + model id
- **MQTT broker** host / port / credentials / topic prefix

The Settings page is the single source of truth. Live Agent and AI-Camera Playground reuse the configured Gemini model (with `-live*` suffixes stripped for non-Live calls).

## Project layout

```
PWDemoMaster/
├── backend/
│   ├── requirements.txt
│   └── app/
│       ├── main.py
│       ├── core/state.py             persistent settings
│       ├── services/mqtt.py          MQTT singleton (subscribes to Frigate topics)
│       ├── knowledge/homeassistant.py HA control capabilities catalog
│       └── routers/
│           ├── frigate.py            cameras, events, motion WS
│           ├── homeassistant.py      areas, entities, services, knowledge
│           ├── live_agent.py         Gemini Live WS + HA tool calls
│           ├── ai_camera.py          Playground WS + vision rule runner
│           └── mqtt.py               MQTT broker config + health
├── frontend/
│   ├── index.html
│   ├── styles.css
│   ├── app.js
│   ├── live-agent.js                 mic/audio + WS for Live Agent
│   └── assets/
├── data/                             auto-created; holds state.json
├── docs/HOMEASSISTANT.md             HA API reference + capability map
├── CLAUDE.md                         project context for Claude Code sessions
├── run.sh / run.ps1 / run.bat        cross-platform runners
└── README.md
```

## Cross-machine workflow (Mac + Windows via GitHub)

1. **Mac (first time):**

   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<you>/pw-demo-master.git
   git push -u origin main
   ```

2. **Windows (first time):**

   ```powershell
   git clone https://github.com/<you>/pw-demo-master.git
   cd pw-demo-master
   .\run.ps1
   ```

3. **Day-to-day on either machine:**

   ```bash
   git pull       # before working
   # ...edit...
   git add .
   git commit -m "describe change"
   git push
   ```

`data/state.json` is gitignored, so each machine keeps its own credentials. The code, knowledge, scripts, and assets all sync.
