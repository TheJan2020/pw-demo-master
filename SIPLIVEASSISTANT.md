# SIP Live Assistant

End-to-end guide for the feature that lets a caller dial a phone number and
talk to a **Gemini Live**-powered AI agent. The agent can see selected
Frigate cameras, drive Home Assistant, and answer questions naturally over a
regular SIP call.

---

## What it is

A backend service inside this FastAPI app that accepts an `AudioSocket` TCP
connection from FreePBX, opens a Gemini Live session per call, and bridges
audio between the two. No browser or WebRTC involved — the caller uses any
ordinary SIP softphone/desk phone, and the AI answers like a human would.

```
[ phone ] ──SIP/RTP──► [ FreePBX VM ] ──AudioSocket TCP──► [ FastAPI service ]
                                                                  │
                                                                  ├─► Gemini Live (audio + video frames)
                                                                  ◄── Gemini Live (audio replies)
                                                                  │
                                                                  ├─► Frigate (snapshots, 1 fps per camera)
                                                                  └─► Home Assistant (tool calls)
```

What the AI can do during a call:

- Talk naturally back and forth (Gemini Live realtime audio).
- See selected Frigate cameras and describe what's on them ("there's one
  person at the front door"). One JPEG per second per camera is streamed in
  round-robin.
- Control Home Assistant — turn lights on/off, query sensor states, etc. —
  when HA tools are enabled.
- Run for up to a configurable max duration before auto-hanging-up.

---

## Prerequisites

- **FreePBX 17** (or any Asterisk 18+) on a reachable host.
  `app_audiosocket.so` must be installed (it is, on the FreePBX 17 distro).
- **Gemini API key** with access to a Live-capable model (e.g.
  `gemini-3.1-flash-live-preview`). Configured in
  **Settings → Gemini Live Agent**.
- **At least one SIP extension registered** that you can use to dial in
  (any softphone — Linphone, MicroSIP, iPhone dialer over a SIP app, etc.).
- **Network reachability** — the FreePBX VM must be able to open a TCP
  connection from `<your-extension's host>` to the FastAPI machine on the
  configured port (default `8090`).

Optional:

- **Frigate** configured in Settings — required only if you want the agent
  to see cameras.
- **Home Assistant** configured in Settings — required only if you want the
  agent to control devices.

---

## Quick start

### 1. Enable the service

1. Open the app at **http://localhost:8080** (or wherever).
2. Go to **SIP Phone → Live Assistant**.
3. Toggle **Enable service** ON.
4. Leave **Bind host** as `0.0.0.0` (listens on every interface).
5. Leave **Port** as `8090` unless something else is using it.
6. Click **Save & apply**.

The status pill should read "Listening on `0.0.0.0:8090` · 0 active call(s)".

Confirm from a terminal on the FastAPI host:

```powershell
# Windows
netstat -ano | findstr 8090
```

```bash
# macOS / Linux
lsof -iTCP:8090 -sTCP:LISTEN
```

You want to see `0.0.0.0:8090 ... LISTENING`.

### 2. Allow inbound on the firewall

The FreePBX VM will open a TCP connection *into* the FastAPI host on the
configured port. Open it.

**Windows**, as administrator:

```powershell
New-NetFirewallRule -DisplayName "SIP Live Assistant AudioSocket" `
                    -Direction Inbound -LocalPort 8090 -Protocol TCP `
                    -Action Allow -RemoteAddress 192.168.100.0/24
```

(Restrict `-RemoteAddress` to just your PBX's `/32` for tighter scoping.)

**macOS**: System Settings → Network → Firewall is fine on default settings
for LAN traffic. If your firewall is enabled, add an exception for the
Python process.

### 3. Wire up FreePBX

This is the previous Claude session's setup (preserved verbatim — no rework
needed if you already have it):

#### Custom Destination

**Admin → Custom Destinations → Add**

| Field | Value |
|---|---|
| Target | `pwdemo-live-agent,s,1` |
| Description | `Live Agent` |
| Notes | (blank) |

Submit.

#### Misc Application

**Applications → Misc Applications → Add**

| Field | Value |
|---|---|
| Enabled | Yes |
| Description | `Live Agent` |
| Feature Code | `9999` |
| Destination | Custom Destinations → Live Agent |

Submit → **Apply Config**.

#### Custom dialplan

SSH to the FreePBX VM and put this in `/etc/asterisk/extensions_custom.conf`:

```ini
[pwdemo-live-agent]
exten => s,1,NoOp(PW Demo Live Agent answered)
 same => n,Answer()
 same => n,Wait(0.3)
 same => n,Set(AUDIOSOCKET_UUID=11111111-1111-1111-1111-111111111111)
 same => n,AudioSocket(${AUDIOSOCKET_UUID},<your-fastapi-host-ip>:8090)
 same => n,Hangup()
```

Replace `<your-fastapi-host-ip>` with the LAN IP of the machine running
FastAPI (e.g. `192.168.100.25`). It must be reachable from the FreePBX VM.

Reload Asterisk's dialplan:

```bash
sudo asterisk -rx "dialplan reload"
sudo asterisk -rx "dialplan show s@pwdemo-live-agent"
```

The second command should list all 6 steps of the extension. If it doesn't,
the file didn't save or the syntax is off.

### 4. Dial it

From any registered SIP extension, dial **`9999`**. You should hear the
greeting within a couple of seconds, then be able to talk to the agent.
Active calls show up live on the **SIP Phone → Live Assistant** page with
transcripts.

---

## Configuration reference

All settings live on the **SIP Phone → Live Assistant** page and persist in
`data/state.json`. Reload-friendly — saving applies immediately without an
app restart.

| Setting | State key | Default | What it does |
|---|---|---|---|
| Enable service | `sla_enabled` | `false` | Starts / stops the AudioSocket listener. |
| Bind host | `sla_bind_host` | `0.0.0.0` | Interface to listen on. Use `127.0.0.1` if the PBX runs on the same host. |
| Port | `sla_bind_port` | `8090` | TCP port. Must match the `AudioSocket(uuid,host:port)` value in the dialplan. |
| System prompt | `sla_system_prompt` | (built-in) | The agent's persona + house rules. HA capabilities are auto-appended when **Enable HA tools** is on. |
| Greeting | `sla_greeting` | `Hello, …` | Spoken by the agent when the call connects. Leave blank to let it improvise. |
| Voice | `sla_voice` | `Aoede` | Which Gemini Live prebuilt voice the agent speaks with. |
| Max call duration | `sla_max_call_s` | `600` | Auto-hang-up after N seconds. Set `0` for unlimited. |
| Enable HA tools | `sla_enable_ha_tools` | `true` | Lets the agent call `list_home_assistant_entities` and `call_home_assistant_service`. |
| Restrict to HA Areas | `sla_only_areas` | `false` | When on, the agent can only see/control entities assigned to an HA Area. |
| Cameras | `sla_cameras` | `[]` | Frigate cameras the agent receives video frames from during a call. Round-robin at ~1 fps each. |

---

## Camera vision

Selected cameras stream into the same Gemini Live session as JPEG frames.
The agent's system prompt is auto-extended with a "Camera vision" section
that lists which cameras it has access to. You can then ask things like:

> "Is anyone at the front door right now?"
> "How many cars are in the driveway?"
> "Describe what you see on the office cam."

Implementation:

- Frames pulled via Frigate's HTTP API at `h=480`.
- Sent through `session.send_realtime_input(video=Blob(..., mime_type="image/jpeg"))`.
- Round-robin: each camera gets a frame every (N × 1 s) where N is the
  number of selected cameras.
- No frames are sent if zero cameras are selected (free Gemini quota).

---

## Audio quality tips

The AudioSocket path is **slin (16-bit PCM, 8 kHz mono)** by default —
telephone bandwidth. To get closer to natural-sounding voice:

### Force G.722 between the phone and Asterisk

G.722 is a wideband (16 kHz) codec. If both the phone and Asterisk agree on
it, the audio between them stays wideband. (The AudioSocket leg is still
8 kHz; quality gains come from clearer caller→Asterisk transit.)

1. **Settings → Asterisk SIP Settings → General SIP Settings → Audio Codecs**:
   drag **G.722** to the top, above ulaw/alaw. Submit + Apply Config.
2. Verify on the VM:
   ```bash
   sudo asterisk -rx "pjsip show endpoint <ext>" | grep "^ allow"
   ```
   Expect `(g722|ulaw|alaw|…)` — G.722 first.
3. On the softphone, enable G.722 in its codec preferences and move it to
   the top.

### Free softphones that include G.722

Zoiper's free tier excludes G.722. These don't:

- **Linphone** (iOS / macOS / Windows / Android / Linux — same project for
  all platforms).
- **MicroSIP** (Windows only, ~5 MB, very lightweight).
- **Grandstream Wave Lite** (iOS / Android).

Free, mature, all include G.722.

---

## Troubleshooting

### Status pill shows "Not running"

You haven't toggled the service on, OR the bind port is in use by something
else. Toggle it; if it still fails, change the port. Check `last_error` via:

```bash
curl http://localhost:8080/api/sip-live-agent/health
```

### Dialing 9999 hangs up immediately

Three layers can break here. Diagnose top-down:

1. **Misc Application points at the wrong destination.** Confirm
   `Applications → Misc Applications → Live Agent → Destination` is set to
   the Custom Destination.
2. **Custom Destination's target is wrong.** Confirm `Admin → Custom
   Destinations → Live Agent` has target `pwdemo-live-agent,s,1`.
3. **The dialplan context doesn't exist.** Run:
   ```bash
   sudo asterisk -rx "dialplan show s@pwdemo-live-agent"
   ```
   Must list all 6 steps. If "no such extension", re-write
   `/etc/asterisk/extensions_custom.conf` and `dialplan reload`.

### "Connection refused" in Asterisk log

The FastAPI service isn't listening on the host:port in the dialplan.
Either:

- Service not enabled in Settings.
- Bound to `127.0.0.1` but FreePBX is connecting from a different host.
- Firewall on the FastAPI machine blocking inbound.

Test from the FreePBX VM:

```bash
nc -vz <fastapi-host-ip> 8090
```

`succeeded` → service is reachable, the call should connect. Any other
result → fix the network/firewall.

### "Connection timed out"

Wrong IP in the dialplan, or the FastAPI host is asleep. Update the IP and
`dialplan reload`.

### Call connects but the caller hears nothing

The greeting is generated by Gemini reading the configured text. If it's
silent:

- Confirm Gemini API key is set in Settings → Gemini Live Agent.
- Confirm the model in Settings → Gemini Live Agent supports the Live API
  (model name contains `-live-` or is `gemini-3.1-flash-live-preview`).
- Check FastAPI logs for `Gemini loop failed` or model errors.

### Agent replies once, then goes silent

Fixed in current code via per-turn `session.receive()` loop. If you still
see this, the Gemini SDK behaviour changed; the receive task should be
restarted automatically after each turn completes.

### Voice has rhythmic "tong tong" clicks

Was an audio-pacing bug. Current code carries partial frames between
chunks (`_out_leftover` in [services/sip_live_agent.py](backend/app/services/sip_live_agent.py))
and uses monotonic-clock pacing. If you somehow still hear clicks, the
event loop is starved by something else — check for CPU-heavy tasks.

### Agent keeps interrupting itself mid-sentence

Acoustic echo from the phone speaker → mic → Gemini → VAD-triggers. The
half-duplex echo gate in `_send_audio` (the `echo_until` timestamp) drops
caller audio while the agent is speaking + 350 ms tail.

If your phone has bad AEC and this still happens, increase the tail
in `_send_audio()` from `0.35` to `0.6` (locally). Trade-off: harder for
the caller to interrupt.

### Camera questions don't get accurate answers

- Confirm the cameras are ticked on the Live Assistant page AND that the
  agent's system instruction shows them. Check `/api/sip-live-agent/config`
  returns them in `cameras: [...]`.
- Frigate must be reachable from the FastAPI host (the snapshot fetch goes
  through this app, not through Asterisk).
- Latency: frames arrive at ~1 fps per camera. If you have 4 cameras
  selected, each gets refreshed every 4 s. Very recent changes may not be
  reflected.

---

## Architecture details (for developers)

### Files

| File | What it does |
|---|---|
| [services/sip_live_agent.py](backend/app/services/sip_live_agent.py) | TCP server + per-call `CallSession` + Gemini Live bridge. |
| [routers/sip_live_agent.py](backend/app/routers/sip_live_agent.py) | REST config + status + WebSocket for live UI updates. |
| [core/state.py](backend/app/core/state.py) | All `sla_*` fields persisted to `data/state.json`. |
| Frontend `renderSipLiveAssistant` in [app.js](frontend/app.js) | The settings page + active-calls + history. |

### AudioSocket protocol

Binary framed, big-endian length:

```
[TYPE:1 byte] [LEN:2 bytes BE] [PAYLOAD:LEN bytes]
```

| TYPE | Meaning |
|---|---|
| `0x00` | Hangup (no payload). |
| `0x01` | UUID (16 bytes — sent once at the start of the connection). |
| `0x02` | DTMF (1 byte ASCII digit). |
| `0x03` | Error (variable-length string from Asterisk). |
| `0x10` | Audio — slin (16-bit signed-linear PCM, 8 kHz mono, little-endian on the wire). |

### Per-call data flow

```
Asterisk → _read_loop → audio_in queue (16k PCM, upsampled)
                                │
                                ▼
                          Gemini Live (audio + video frames)
                                │
                                ▼
audio_out queue (24k PCM) ← receive()
       │
       ▼
_write_loop ── downsample 24k → 8k ── _out_leftover buffer ── _send_audio
                                                                    │
                                                          (paced at 20 ms/frame
                                                           via monotonic clock)
                                                                    ▼
                                                              Asterisk
```

### Echo gate

`_send_audio()` pushes `echo_until` to `time.time() + (n_frames × 20 ms) + 350 ms`
every write. `_read_loop()` drops caller audio while `time.time() < echo_until`.

Half-duplex by design — the trade-off is the caller can't barge in
mid-sentence. Tail can be shortened if barge-in matters more than smoothness.

### Tool calls

When the agent decides to call a Home Assistant tool (`list_home_assistant_entities`
or `call_home_assistant_service`), the `receive()` task picks up the
`tool_call` field on the response message, executes the tool against HA via
the same logic the Live Agent page uses ([routers/live_agent.py](backend/app/routers/live_agent.py)),
and sends `FunctionResponse` back into the Gemini session. Tool execution
also broadcasts a `call_tool` event to subscribed WebSocket clients so the
UI can show it.

### Concurrency model

Per call:

- `_read_loop()` — reads frames from Asterisk, pushes upsampled audio to `audio_in`.
- `_write_loop()` — pops audio from `audio_out`, downsamples + buffers + paces, writes to Asterisk.
- `_gemini_loop()` — runs Gemini Live session; inside it three coroutines are
  `asyncio.gather`'d:
  - `feed()` — pulls from `audio_in`, sends to Gemini.
  - `receive()` — receives from Gemini, pushes to `audio_out` + emits
    transcript / tool events.
  - `stream_cameras()` — round-robins JPEG frames from selected cameras.

Call ends when any of: the caller hangs up, `max_call_s` elapses, the
service is stopped, or a fatal error is raised.

---

## Known limitations

- **Half-duplex** — you can't truly interrupt the agent mid-sentence. The
  agent has to finish its current utterance + 350 ms tail before your audio
  gets through.
- **8 kHz inside** — `AudioSocket` defaults to slin (8 kHz). For wideband
  end-to-end you'd need to force `slin16` in the dialplan and update the
  service to use 640-byte frames. The current code targets 8 kHz to match
  the most common case.
- **Single hardcoded UUID** — the dialplan uses
  `11111111-1111-1111-1111-111111111111` for all calls. Multiple
  simultaneous calls would all share the same UUID label (still each get
  their own TCP connection and session — only the UUID label collides).
- **No call recording** — transcripts are kept in memory in the
  `CallSession` and exposed via the WebSocket / status endpoints, but the
  raw audio is not saved.
- **No SIP-side authentication beyond Asterisk's regular extension auth** —
  treat the AudioSocket port as trusted on the LAN. Don't expose it
  publicly.

---

## API endpoints

| Method + path | Purpose |
|---|---|
| `GET /api/sip-live-agent/config` | Returns the SlaConfigOut payload (current settings). |
| `POST /api/sip-live-agent/config` | Updates one or more settings (any subset of fields). Triggers `apply_config()`. |
| `GET /api/sip-live-agent/health` | One-line status pill content. |
| `GET /api/sip-live-agent/status` | Detailed: status + active calls + history (40 most recent). |
| `WS /api/sip-live-agent/ws` | Push channel: `snapshot`, `status`, `call_started`, `call_ended`, `call_transcript`, `call_tool`. |

---

## Rolling it back

If you want to disable the feature entirely:

1. **App side:** SIP Phone → Live Assistant → toggle **Enable service** OFF
   → Save. The TCP listener stops.
2. **FreePBX side:** Applications → Misc Applications → Live Agent → set
   **Enabled = No** (keeps the config; disables the feature code) — or
   delete the row to remove `9999` entirely. The Custom Destination and
   `extensions_custom.conf` block can stay parked, they cost nothing.

Everything else (Gemini key, HA config, Frigate, MQTT) is independent and
keeps working with the rest of the app.
