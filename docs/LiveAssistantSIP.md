# Bridging FreePBX → Gemini Live (SIP Phone · Live Assistant)

This guide gets you to: **call an extension on your FreePBX, have a
Gemini Live AI agent answer, hold a natural voice conversation, and let
it drive Home Assistant via tool calls.**

It's the next layer on top of [SIP.md](SIP.md). That doc gets you a PBX
running on Proxmox; this doc bridges that PBX to the Gemini Live API
running inside PW Demo Master's backend.

---

## 1. How the pieces fit

```
   ┌──────────────────┐                  ┌───────────────────┐
   │  Caller (SIP/    │  SIP / RTP       │  FreePBX +        │
   │  WebRTC / etc.)  │ ───────────────▶ │  Asterisk         │
   └──────────────────┘                  │                   │
                                         │  ext 9999 →       │
                                         │  AudioSocket()    │
                                         └───────┬───────────┘
                                                 │  TCP  (chan_audiosocket
                                                 │       wire protocol)
                                                 │  caller audio  ← 8 kHz slin
                                                 │  agent audio   → 8 kHz slin
                                                 ▼
                                  ┌──────────────────────────┐
                                  │  PW Demo Master backend  │
                                  │  services/sip_live_agent │
                                  │                          │
                                  │  - 1 TCP listener        │
                                  │  - per-call CallSession  │
                                  │  - audioop resample      │
                                  │    8k ↔ 16k ↔ 24k        │
                                  └───────┬──────────────────┘
                                          │ Gemini Live WebSocket
                                          │ (audio 16k → / audio 24k ←)
                                          ▼
                                ┌────────────────────────────┐
                                │  Gemini Live API (Google)  │
                                │  - voice in/out            │
                                │  - HA tool calls           │
                                └────────────────────────────┘
```

**Key choice — why AudioSocket and not a Python SIP stack?**
Asterisk is already doing the hard part (SIP signalling, RTP, codec
transcoding, NAT traversal). `AudioSocket()` is a dialplan application
that opens a TCP socket and hands you cooked PCM audio in both
directions. Our backend never speaks SIP or RTP — it just deals with
framed audio over TCP, which is straightforward in asyncio Python and
maps cleanly to Gemini Live's `send_realtime_input(audio=...)` call.

If you ever need to bypass Asterisk entirely (e.g. point a hardware SIP
phone directly at the agent), swap in `pjsua2` or `aiortc` — but for
this stack, AudioSocket is the right tool.

---

## 2. Prerequisites

Before starting:

- **FreePBX** running and reachable (this guide is written against the
  `192.168.100.45` instance — replace with your IP throughout).
- **PW Demo Master backend** running on a machine that the FreePBX can
  reach on TCP (default port `8090`). They can be on the same LAN, or
  the backend can be `localhost` if FreePBX and the backend run in the
  same VM/container.
- **Gemini API key** configured in **Settings → Gemini Live Agent** (the
  Live Assistant reuses it).
- **Home Assistant** configured in Settings (only required if you want
  the agent to control HA devices over the call).

---

## 3. FreePBX side — enable AudioSocket

The `chan_audiosocket` module is bundled with Asterisk 18+ and is
included in FreePBX Distro. We just need to load it and wire the
dialplan.

### 3.1 Confirm modules are present

SSH into FreePBX, then:

```bash
asterisk -rx "module show like audiosocket"
```

You should see two modules — `app_audiosocket.so` and
`res_audiosocket.so`. If they're not listed, install/load them:

```bash
asterisk -rx "module load res_audiosocket.so"
asterisk -rx "module load app_audiosocket.so"
```

Permanent (so a reboot doesn't drop them): edit
`/etc/asterisk/modules.conf` and ensure either `autoload=yes` (the
default in FreePBX) or explicit `load => res_audiosocket.so` /
`load => app_audiosocket.so`.

### 3.2 Add the dialplan snippet

Edit `/etc/asterisk/extensions_custom.conf` and add:

```ini
; --------------------------------------------------------------
; AI Agent over AudioSocket
;
; Route any call here (custom destination or by extension) to bridge
; the call into PW Demo Master's Live Assistant service.
;
; Change BRIDGE_HOST / BRIDGE_PORT to wherever the demo backend runs.
; UUID can be any 16-byte hex; we generate a fresh one per call so the
; backend can identify it.
; --------------------------------------------------------------
[ai-agent-custom]
exten => s,1,NoOp(Sending call to PW Demo Master Live Assistant)
 same => n,Answer()
 same => n,Set(BRIDGE_HOST=192.168.100.10)        ; ← demo backend IP
 same => n,Set(BRIDGE_PORT=8090)
 same => n,Set(CALL_UUID=${SHELL(uuidgen | tr -d '-')})
 same => n,Set(CALL_UUID=${CALL_UUID:0:32})
 same => n,Verbose(1,AudioSocket → ${BRIDGE_HOST}:${BRIDGE_PORT} uuid=${CALL_UUID})
 same => n,AudioSocket(${CALL_UUID},${BRIDGE_HOST}:${BRIDGE_PORT})
 same => n,Hangup()
```

> Set **`BRIDGE_HOST`** to whatever IP the PW Demo Master backend is
> reachable at *from the FreePBX VM*. If both run on the same machine,
> `127.0.0.1` is fine. From the example FreePBX at
> `192.168.100.45` to a backend on the same LAN, use that machine's
> LAN IP.

Reload the dialplan:

```bash
asterisk -rx "dialplan reload"
```

### 3.3 Create the extension in the FreePBX UI

We want a normal extension number (say **9999**) that, when dialled,
jumps into the `ai-agent-custom` context above.

1. **Admin → Custom Destinations → Add Destination**
   - Description: `AI Agent`
   - Target: `ai-agent-custom,s,1`
   - Return: `No`
   - Submit + Apply Config.
2. **Applications → Misc Applications → Add Misc Application**
   - Description: `AI Agent`
   - Feature Code: `9999`
   - Destination: **Custom Destinations · AI Agent**
   - Submit + Apply Config.

That's it on the PBX side. Dial **9999** from any registered extension
(your softphone tab from [SIP.md](SIP.md), a physical SIP phone, etc.)
and the call lands in our backend.

### 3.4 Open the firewall

If FreePBX has its own firewall (the SNG7 distro does), allow outbound
TCP to your backend's AudioSocket port. The Sangoma firewall by default
allows all outbound traffic — only inbound traffic is filtered — so this
usually doesn't need anything special. If you've locked it down, add
`192.168.100.10:8090` (or wherever your backend listens) to the
allow-out list.

On the backend host, allow inbound TCP `8090` from the FreePBX IP:

```bash
# macOS / Linux running the demo backend
sudo ufw allow from 192.168.100.45 to any port 8090 proto tcp
# or just: sudo ufw allow 8090/tcp
```

---

## 4. PW Demo Master side — configure the Live Assistant

1. Open the demo app, go to **SIP Phone → Live Assistant**.
2. Settings card:
   - **Enable service** ✓
   - **Bind host**: `0.0.0.0` (listens on every interface)
   - **Port**: `8090` (matches the `BRIDGE_PORT` set above)
   - **System prompt**: rewrite to whatever persona/job you want — e.g.
     "You are the receptionist for Primewave Demo. Greet the caller,
     ask what they need, and if they want device control use the HA
     tools." The Home Assistant capability catalog is appended
     automatically when **Enable HA tools** is on, so you don't need
     to spell out the catalog of services yourself.
   - **Greeting**: optional one-liner the agent will speak first (e.g.
     "Hello, you've reached Primewave. How can I help?"). Leave blank
     to let the agent improvise.
   - **Voice**: pick from Aoede / Puck / Charon / Kore / Fenrir.
   - **Max call duration**: hard hangup at N seconds. `0` = no limit.
   - **Enable HA tools** ✓ — gives the agent `list_home_assistant_entities`
     and `call_home_assistant_service` function calls.
   - **Restrict to entities assigned to an HA Area**: optional safety
     filter; only entities under a named HA Area are visible to the
     agent (same semantics as the Smart Home Live Agent).
3. Hit **Save & apply**. The Service pill below should flip to
   *Listening on 0.0.0.0:8090 · 0 active*.

The topbar's `SIP:` pill keeps reflecting your *softphone* register
status — the Live Assistant status lives only on this page.

---

## 5. Try it

1. On your laptop, open the demo's **SIP Phone → Extension** page (or
   use a regular SIP softphone) registered to an extension on the same
   FreePBX.
2. Dial **9999**.
3. The Active calls panel on the Live Assistant page should light up
   within a second with a `LIVE` row showing the calling extension's
   IP:port.
4. As you talk, the row's *Heard:* line streams Gemini's transcription
   of your speech; the *Said:* line streams the transcription of what
   the agent is saying back.
5. Try "*Turn the kitchen lights on*" or "*What lights do I have?*" —
   you'll see HA tool calls fire in the backend log
   (`logger.info("call … tool_call …")`) and the lights actually change.

When the call ends, the row moves to **Recent calls** with the final
duration and both transcripts persisted (in memory, last 40 entries).

---

## 6. Data flow per call

This is what each TCP connection actually carries:

1. Asterisk dials our TCP listener.
2. Asterisk sends a single **UUID frame** (`type=0x01`, 16 bytes) so we
   have a stable call identifier.
3. Both sides start exchanging **audio frames** (`type=0x10`,
   variable-length payload of signed-linear 16-bit mono samples at
   8 kHz, big-endian on the wire, ≈ 20 ms per frame = 320 bytes).
4. Either side can send **DTMF** (`type=0x02`) or **error** (`type=0x03`).
5. Either side closes with **hangup** (`type=0x00`).

Inside the backend:

- Caller audio (8 kHz) is upsampled to 16 kHz via `audioop.ratecv` and
  pushed to `session.send_realtime_input(audio=Blob(...))`.
- Gemini's reply audio arrives as 24 kHz PCM; we downsample to 8 kHz
  and write it back to the TCP stream in 20 ms frames.
- Tool calls fan out to the Home Assistant helper functions (which
  mirror those in `services/live_agent.py`).
- `input_audio_transcription` / `output_audio_transcription` are
  enabled in the LiveConnectConfig so the UI gets a running transcript
  for free — without paying for separate STT.

---

## 7. Backend internals — where to look

| Concern | File |
| --- | --- |
| TCP server, per-call state machine, resampling, Gemini loop | [backend/app/services/sip_live_agent.py](../backend/app/services/sip_live_agent.py) |
| REST + WebSocket API for the management page | [backend/app/routers/sip_live_agent.py](../backend/app/routers/sip_live_agent.py) |
| Persistent settings (system prompt, voice, port, etc.) | `sla_*` fields in [backend/app/core/state.py](../backend/app/core/state.py) |
| Tool catalog the agent can call | [backend/app/knowledge/homeassistant.py](../backend/app/knowledge/homeassistant.py) |
| Management UI | `renderSipLiveAssistant` in [frontend/app.js](../frontend/app.js) |
| FastAPI lifespan that starts/stops the service | [backend/app/main.py](../backend/app/main.py) |

The service is **only** brought up if `state.sla_enabled` is true — the
backend boots fine without it, the management page can flip it on/off
without restarting the server, and changing the bind port re-binds on
the fly.

---

## 8. Troubleshooting

### Service won't start — `bind 0.0.0.0:8090: ...`
Port already in use, or you don't have permission. Check with `lsof
-i :8090` on the backend host. Change the port in the Live Assistant
settings and the matching `BRIDGE_PORT` in `extensions_custom.conf`.

### Dialing 9999 plays silence / call hangs up immediately
Watch the Asterisk console: `asterisk -rvvv` then dial. You should see
`AudioSocket → ... uuid=...`. If you see *"chan_audiosocket: Failed to
connect to ..."*:

- The `BRIDGE_HOST` is wrong, or the backend isn't reachable.
- The backend isn't listening (Live Assistant disabled or crashed).
- Firewall blocking inbound TCP.

Verify from the FreePBX shell: `nc -zv 192.168.100.10 8090`.

### Caller hears choppy / muffled audio
Two common causes:
- **Network jitter** between FreePBX and the backend. Both should be
  on the same LAN; running the backend on a different continent will
  not work.
- **Resampling artefacts**. We use `audioop.ratecv` (linear-interp);
  it's fine for voice but not audiophile-grade. If you need better,
  swap in `scipy.signal.resample_poly` (one-line replacement in
  `CallSession._read_loop` / `_write_loop`).

### Agent doesn't reply, but service log shows audio flowing
Open `/api/sip-live-agent/health` directly — if it says
`Gemini API key not configured` or `Listening … 0 active` while a call
is supposedly in progress, the per-call task crashed. Backend logs
under `sip_live_agent` will have the traceback. The most common cause
is a Gemini Live API quota / version mismatch — verify the model name
in **Settings → Gemini Live Agent** is Live-capable (the same model
the Smart Home Live Agent uses).

### One-way audio (you hear the agent; agent doesn't hear you)
`audioop` state was never initialised. This shouldn't happen because
we lazily init `_upstate` to `None` and `ratecv` accepts that — but if
you've forked the code, double-check the per-direction state isn't
shared.

### Multiple concurrent calls
Each TCP connection gets its own `CallSession` and its own Gemini Live
WebSocket. Tested up to a handful concurrently; if you push past
~20 you'll start hitting Gemini Live concurrency limits on the API
side, not in our code.

---

## 9. Replicating onto a fresh machine

Order of operations on a brand-new install:

1. Clone the repo, follow [README.md](../README.md) to get the demo
   running (`./run.sh` or `.\run.ps1`).
2. **Settings → Gemini Live Agent**: paste your Gemini API key, set the
   model id.
3. **Settings → Home Assistant**: URL + long-lived token, if you want
   the agent to control devices.
4. **Settings → MQTT broker**: optional, only if Frigate motion is in
   scope.
5. **Settings → SIP softphone**: only needed if you also want to make
   calls *from* the browser; not required for the Live Assistant
   server-side.
6. Provision FreePBX per [SIP.md](SIP.md). Confirm it's up.
7. Apply **§3** of this doc on FreePBX (the dialplan + custom
   destination).
8. **SIP Phone → Live Assistant** in the demo: tick *Enable service*,
   pick a port, write a prompt, hit Save & apply.
9. Dial 9999 from a softphone.

All settings — prompt, voice, greeting, port — live in
`data/state.json`. You can copy that file between machines to clone
the Live Assistant config without re-typing.

(`data/state.json` is gitignored on purpose — see [README.md](../README.md)
for the per-machine credentials story.)

---

## 10. What we deliberately don't do

- **No on-disk recording of call audio.** Transcripts are kept in
  memory for the last 40 calls. Adding `pydub` + a WAV writer is a
  half-day's work if you ever need recordings.
- **No call queueing.** Calls answer immediately if Live Assistant is
  enabled; if it's disabled or unreachable, Asterisk falls through to
  whatever you set as the post-AudioSocket dialplan step (the
  `Hangup()` line in §3.2).
- **No outbound calling from the agent.** This service only answers
  inbound calls. Letting the agent place outbound calls would mean
  signalling SIP from the backend (pjsua2) — a separate piece.
- **No video.** AudioSocket is audio-only by design. Video calls
  through Asterisk would need a different channel driver.
