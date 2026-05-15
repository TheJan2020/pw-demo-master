# SIP Live Representative

End-to-end guide for **Lena**, Primewave's customer-facing AI sales / support
rep that answers SIP calls in Lebanese Arabic, talks about Primewave's
offerings, and collects structured information from callers (name, address,
contact, interests, project phase…). Every call is permanently logged with
its transcript and the structured data the agent gathered.

---

## What it is

A second backend service inside this FastAPI app that mirrors the
[SIP Live Assistant](SIPLIVEASSISTANT.md) plumbing but is tailored to be a
*sales / support rep* rather than a smart-home controller. It:

- Listens on its own TCP port (default `8091`).
- Has its own FreePBX feature code (default `8888`).
- Speaks Lebanese Arabic by default (configurable persona).
- Reads from a **Knowledge base** describing Primewave's products / services.
- Has a **dynamic information schema** — you describe what data you want to
  collect from each caller, and Lena gathers it conversationally.
- Persists **every** call (transcript + collected info) to disk in JSONL
  format. The UI shows a real-time table where columns come from the
  information schema and rows fill in as calls happen.

```
[ phone ] ──SIP/RTP──► [ FreePBX VM ] ──AudioSocket TCP──► [ FastAPI service ]
                                                                 │
                                                                 ├─► Gemini Live (audio in/out)
                                                                 ├─► save_caller_information(...)   ◄── tool calls
                                                                 │
                                                                 └─► data/sip_live_rep/calls.jsonl  (transcript + collected info per call)
```

---

## How it differs from SIP Live Assistant

| | SIP Live Assistant (`9999`) | SIP Live Representative (`8888`) |
|---|---|---|
| Purpose | Smart-home control + general assistant | Sales/support agent for Primewave |
| Default language | English | Lebanese Arabic |
| HA tools | Yes — can control HA entities | No |
| Camera vision | Yes — round-robin Frigate frames | No |
| Knowledge base | Free-form system prompt | Separate persona + knowledge base fields |
| Info collection | None | Dynamic schema with function-call tool |
| Call history | In-memory, last 40 | **Persistent on disk**, all calls forever |
| Bind port | 8090 | 8091 |
| Custom dialplan context | `pwdemo-live-agent` | `pwdemo-live-rep` |
| AudioSocket UUID label | `11111111-…-1` | `22222222-…-2` |

Audio pipeline (echo gate, monotonic pacing, partial-frame buffering) is
identical — proven plumbing reused.

---

## Prerequisites

- **FreePBX 17** (or Asterisk 18+) with `app_audiosocket.so` installed.
- **Gemini API key** with access to a Live-capable model (e.g.
  `gemini-3.1-flash-live-preview`). Configure in **Settings → Gemini Live Agent**.
- **At least one SIP extension** registered to call from.
- **Network reachability** — FreePBX VM must be able to reach the FastAPI
  host on the bind port (default `8091`).

---

## Quick start

### 1. Enable the service

1. Open the app → **SIP Phone → Live Representative**.
2. Toggle **Enable service** ON.
3. Leave **Bind host** as `0.0.0.0`.
4. Leave **Port** as `8091`.
5. Click **Save & apply**.

The pill should read "Listening on `0.0.0.0:8091` · 0 active call(s)".

Verify on Windows:

```powershell
netstat -ano | findstr 8091
```

### 2. Allow inbound on the firewall

```powershell
New-NetFirewallRule -DisplayName "SIP Live Rep AudioSocket" `
                    -Direction Inbound -LocalPort 8091 -Protocol TCP `
                    -Action Allow -RemoteAddress 192.168.100.0/24
```

### 3. Wire up FreePBX

#### Custom Destination

**Admin → Custom Destinations → Add**

| Field | Value |
|---|---|
| Target | `pwdemo-live-rep,s,1` |
| Description | `Live Representative` |

Submit.

#### Misc Application

**Applications → Misc Applications → Add**

| Field | Value |
|---|---|
| Enabled | Yes |
| Description | `Live Representative` |
| Feature Code | `8888` |
| Destination | Custom Destinations → Live Representative |

Submit → **Apply Config**.

#### Custom dialplan

Append (don't overwrite the existing `[pwdemo-live-agent]` block from
SIPLIVEASSISTANT.md) to `/etc/asterisk/extensions_custom.conf`:

```bash
sudo tee -a /etc/asterisk/extensions_custom.conf > /dev/null << 'EOF'

[pwdemo-live-rep]
exten => s,1,NoOp(PW Demo Live Rep answered)
 same => n,Answer()
 same => n,Wait(0.3)
 same => n,Set(AUDIOSOCKET_UUID=22222222-2222-2222-2222-222222222222)
 same => n,AudioSocket(${AUDIOSOCKET_UUID},<your-fastapi-host-ip>:8091)
 same => n,Hangup()
EOF
sudo asterisk -rx "dialplan reload"
sudo asterisk -rx "dialplan show s@pwdemo-live-rep"
```

Replace `<your-fastapi-host-ip>` with the same address you used for
`pwdemo-live-agent`. The last command should print all 6 dialplan steps.

### 4. Dial it

Dial **`8888`** from any registered SIP extension. Lena should greet you in
Lebanese Arabic. Speak naturally; she'll ask for your information as the
conversation progresses.

---

## Configuration reference

All settings live on the **SIP Phone → Live Representative** page and
persist in `data/state.json`. Changes apply on the next call without
restarting anything.

| Setting | State key | Default | What it does |
|---|---|---|---|
| Enable service | `slr_enabled` | `false` | Starts / stops the AudioSocket listener. |
| Bind host | `slr_bind_host` | `0.0.0.0` | Interface to listen on. |
| Port | `slr_bind_port` | `8091` | TCP port — must match the `AudioSocket(uuid,host:port)` in the dialplan. |
| Persona / system prompt | `slr_system_prompt` | (Arabic Lebanese persona) | Who Lena is and how she speaks. |
| Knowledge base | `slr_knowledge` | (Primewave services description) | Reference material Lena uses to answer questions. Free-form Arabic/English text. |
| Information to collect | `slr_info_schema` | (5-field list) | Structured fields Lena tries to gather. Editable as a row-by-row form in the UI; serialized as a list of `{name, label, description}` objects. |
| Greeting | `slr_greeting` | "أهلا فيك معنا، أنا لينا…" | Spoken the moment a call connects. |
| Voice | `slr_voice` | `Aoede` | Which Gemini Live prebuilt voice. |
| Max call duration | `slr_max_call_s` | `900` | Auto-hang-up after N seconds (0 = unlimited). |

---

## The three fields explained

### Persona (`slr_system_prompt`)

The agent's behavioural instructions. Default tells Lena to speak Lebanese,
behave like a real human, deflect off-topic questions, refuse to invent
information, and invoke `save_caller_information` whenever she learns
something new.

This is also where you tune *how aggressive* Lena is at collecting info.
The default is conversational; if you want her to be more direct
("اسألي مباشرة عن المعلومات الناقصة قبل ما تنهي المكالمة") add a sentence
to that effect.

### Knowledge base (`slr_knowledge`)

Free-form text describing the company's offerings — products, prices,
process, competitive advantages, FAQs. Lena reads it as reference material
to answer technical questions about Primewave's services.

Use Markdown headings (`##`, `###`) to organise it. Lena will reference
sections naturally during conversation. Update this whenever services
change — no code/restart needed.

### Information to collect (`slr_info_schema`)

A list of `{name, label, description}` rows that describes what data you
want Lena to collect from each caller. The schema becomes:

1. The columns of the **Collected information** table.
2. Part of the system prompt (Lena is told to gather each of these).
3. The **JSON schema** of the `save_caller_information` Gemini function
   tool — Lena calls this function during the call, multiple times, as
   information emerges.

The default 5 fields match what you'd typically need for a Primewave smart
home lead:

| name | label | description |
|---|---|---|
| `name` | الاسم | الاسم الثلاثي للمتصل |
| `address` | العنوان | عنوان أو موقع المشروع |
| `contact` | وسيلة التواصل | رقم هاتف أو إيميل |
| `preference` | الاهتمامات | إضاءة، HVAC، إنتركوم، إلخ |
| `project_phase` | مرحلة المشروع | تصميم، تنفيذ، تجديد |

Add/remove rows freely in the UI; the table columns update on the next
save, and Lena's tool schema updates on the next call.

---

## The collected-information table

Real-time table on the Live Representative page. Columns: **When**,
**Caller**, then one column per row in your information schema.

- Rows for **in-progress** calls show a red **LIVE** badge and fill in
  cells as Lena gathers data (via WebSocket events from the backend).
- Rows for **finished** calls come from disk (`calls.jsonl`) so they
  survive restarts. Loaded as part of the page snapshot.
- Calls with **no collected info** are hidden from the table — they still
  appear in the **Call history** panel below if you want to read their
  transcript.

To export: the underlying `data/sip_live_rep/calls.jsonl` file is plain
JSONL — one call per line — easy to feed into any spreadsheet or data
pipeline.

---

## Call history (transcripts)

Below the collected-info table. One row per past call:

- Click a row to expand and read the full transcript inline (caller +
  agent turns, with timestamps).
- **Load 20 more** for older calls; pagination is server-side via
  `GET /api/sip-live-rep/history?offset=N&limit=20`.
- **Clear history** wipes the JSONL file entirely. The active calls panel
  stays untouched.

Audio is **not** recorded — only the text transcript that Gemini's
input/output transcription emits per turn. This is intentional (smaller
storage, no PII audio at rest, simpler compliance).

---

## How the collection tool works

When a call starts, the backend builds a `genai.types.Tool` whose function
declaration is generated from `slr_info_schema`:

```python
types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="save_caller_information",
        description="Persist information you've gathered from the caller…",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                field["name"]: types.Schema(
                    type=types.Type.STRING,
                    description=field["description"] or field["label"],
                )
                for field in state.slr_info_schema
            },
        ),
    ),
])
```

That tool is passed to `client.aio.live.connect(..., config=cfg)`. Lena
(the model) decides when to call it, with whatever fields she's confirmed
so far. The handler in `receive()` merges every call's args into
`session.collected_info` and pushes a `call_collected` event to all
WebSocket subscribers so the table updates live.

She might call it once at the end ("here's everything I learned") or
multiple times throughout ("just got the name — saving"). Both work.
The tool response is `{"ok": true, "stored": [<keys so far>]}` so Lena can
internally track what's already saved.

---

## Troubleshooting

### Status pill shows "Not running"

Service isn't enabled, OR port is in use by something else (the Live
Assistant also on `8091`? Both bind ports must differ; defaults
are `8090` vs `8091`). Check `last_error` via:

```bash
curl http://localhost:8080/api/sip-live-rep/health
```

### Dialing 8888 hangs up instantly

Same diagnosis tree as Live Assistant:

1. Misc Application → Custom Destination linkage correct?
2. Custom Destination target = `pwdemo-live-rep,s,1`?
3. `dialplan show s@pwdemo-live-rep` returns all 6 steps?

### Lena doesn't speak Lebanese

She follows the **persona** field verbatim. If she's not, the prompt got
overwritten or simplified. The default opens with "كلامك دايماً باللهجة
اللبنانية" — re-add that line if missing.

### Lena doesn't ask for info

Two possibilities:

- The **info schema is empty** — without fields, the tool isn't created
  and Lena has nothing to gather. Add at least one row.
- The persona doesn't tell her to collect — make sure the default
  "خلال المكالمة، حاولي بشكل طبيعي تجمعي المعلومات" sentence is still in
  the prompt.

If she asks naturally but never calls the tool, add a more explicit
sentence: "كل ما تأكدتي من معلومة، استدعي وظيفة `save_caller_information`
وحطي القيمة بالحقل المناسب".

### Lena collects info but the table stays empty

Check the FastAPI logs for `call abc: collected {…}` entries. If they
appear → the WS event isn't reaching the page; refresh the page.
If they don't appear → the tool isn't being called; tighten the persona.

### Audio quality is muddy

Same fix as Live Assistant — codec preferences. **Settings → Asterisk SIP
Settings → Audio Codecs** → put G.722 first, and use a softphone that
includes G.722 (Linphone, MicroSIP — Zoiper's free tier doesn't).

### Agent self-interrupts on speakerphone

Inherited from Live Assistant — half-duplex echo gate kicks in. If you
need barge-in capability instead, shorten the tail in
`_send_audio()` (currently `0.35`s). Trade-off: more chance of the agent
hearing its own echo and interrupting itself.

---

## API endpoints

| Method + path | Purpose |
|---|---|
| `GET /api/sip-live-rep/config` | Current settings. |
| `POST /api/sip-live-rep/config` | Update settings (partial body OK). Triggers re-bind if host/port changed. |
| `GET /api/sip-live-rep/health` | One-line status. |
| `GET /api/sip-live-rep/status` | Detailed: status + active calls (with `collected` map). |
| `GET /api/sip-live-rep/history?offset=N&limit=20` | Paginated permanent call history (newest first). |
| `DELETE /api/sip-live-rep/history` | Wipe the JSONL file. |
| `WS /api/sip-live-rep/ws` | Push channel: `snapshot`, `status`, `call_started`, `call_transcript`, `call_collected`, `call_ended`. |

### `call_collected` event payload

```json
{
  "type": "call_collected",
  "call_id": "abc12",
  "fields": {
    "name": "علي حسن",
    "contact": "+9613xxxxxxx"
  }
}
```

Fields are merged across multiple events per call — each one carries the
current full set of `collected_info`, not just the new keys.

### `call_ended` event payload

```json
{
  "type": "call_ended",
  "call_id": "abc12",
  "peer": "127.0.0.1:NNNNN",
  "uuid": "22222222...",
  "started_at": 1700000000.0,
  "ended_at": 1700000130.0,
  "duration_s": 130,
  "heard": "<full caller transcript>",
  "spoken": "<full Lena transcript>",
  "turns": [{"role":"agent","text":"...","ts":...}, ...],
  "collected": { "name": "...", "contact": "..." }
}
```

The same object is the one persisted as a line in `calls.jsonl`.

---

## File map

| File | What it does |
|---|---|
| [services/sip_live_rep.py](backend/app/services/sip_live_rep.py) | TCP server, `CallSession`, Gemini Live bridge, function tool, JSONL history. |
| [routers/sip_live_rep.py](backend/app/routers/sip_live_rep.py) | REST config + status + history + WS. |
| [core/state.py](backend/app/core/state.py) | All `slr_*` fields persisted to `data/state.json`. |
| Frontend `renderSipLiveRep` in [app.js](frontend/app.js) | The page renderer (settings + schema editor + active + table + history). |
| `data/sip_live_rep/calls.jsonl` | Persistent call history. One JSON object per line, newest at the bottom. |

---

## Known limitations

- **No raw audio recording.** Transcripts only. Adding WAV-per-call is a
  ~50-line addition (open a `wave.Wave_write` in `CallSession.__init__`,
  feed it the 8 kHz frames in `_read_loop` and `_write_loop`). Out of
  scope for v1; can be added later when needed for compliance / QA.
- **Half-duplex audio.** Inherited from Live Assistant — the caller can't
  truly interrupt Lena mid-sentence. Acceptable for a rep call where the
  agent does most of the talking.
- **Single hardcoded UUID** in the dialplan
  (`22222222-2222-2222-2222-222222222222`). Multiple simultaneous calls
  still each get their own TCP connection and `CallSession`; only the
  UUID label collides — visible only in logs.
- **In-process JSONL append.** Concurrent calls are fine (file is opened
  in append mode per write) but if the file grows enormous (tens of
  thousands of calls), `GET /history` reads it all into memory. Add a
  rotation step or move to SQLite if that becomes a real number.
- **No SIP-side auth beyond Asterisk extension auth.** Don't expose port
  `8091` to the public internet.

---

## Rolling back

To disable:

1. **App side**: SIP Phone → Live Representative → toggle **Enable
   service** OFF → Save. The TCP listener stops.
2. **FreePBX side**: Applications → Misc Applications → Live
   Representative → set **Enabled = No** (keeps the config; disables the
   feature code), or delete to remove `8888`.

The Custom Destination, dialplan block, and `data/sip_live_rep/` folder
can stay parked indefinitely — they cost nothing. To purge persisted
history specifically: **Clear history** button on the page, or delete
`data/sip_live_rep/calls.jsonl`.

---

## Related docs

- [SIPLIVEASSISTANT.md](SIPLIVEASSISTANT.md) — the smart-home variant (extension `9999`).
- [CLAUDE.md](CLAUDE.md) — project-wide architectural decisions.
- [OLLAMA.md](OLLAMA.md) — remote Ollama setup, unrelated to SIP but uses the same Tailscale pattern that makes the Live Rep service reachable from FreePBX over a different network.
