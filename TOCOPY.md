# TOCOPY — bring the other machine up to this session's state

Self-contained checklist for the other environment (office machine).
Follow top-to-bottom. Everything that travels via `git pull` is marked
**[code]**; everything that has to be re-done manually because it lives
outside git is marked **[per-machine]** or **[per-PBX]**.

> Background: this session added supervisor escalation + AMI dial-in
> to the Clinic Live Agent, fixed a batch of persona/voice regressions,
> and tightened the agent's tool layer. Full feature reference lives in
> `DEMOSITEMAP.md` §6c and §6d after the pull — this file is just the
> "do this in order to get it running" checklist.

---

## What's new this session (high-level)

**Live Agent voice + transcript** — echo gate is now always-on, VAD
sensitivity dropped from HIGH→LOW, frontend filters Gemini-mis-transcribed
gibberish. Voice freezes and word-salad transcripts should be substantially
fewer.

**Live Agent persona** — context-first escalation rules, never asks
about gender, today/tomorrow/day-after dates pre-injected, digits spoken
one at a time for IDs/file numbers/phones, slot-grid discipline.

**Supervisor escalation (new feature)** — agent can call a
`flag_for_supervisor(reason, severity)` tool. Flagged calls paint red
on the Dashboard with an Acknowledge button. Operator-editable trigger
keywords + scenarios live on Call Center → Configuration. **Re-flagging
the same cause is allowed and encouraged** (fixed a bug where ack →
re-flag silently failed).

**Supervisor dial-in via AMI (new feature)** — Dashboard rows have a
3-button group (Listen / Whisper / Barge) that issue an Asterisk
Manager Interface `Originate` so a supervisor's PBX extension rings;
on answer they're dropped into the live call via `ChanSpy` with the
matching audio policy. Falls back to copy-to-clipboard on AMI failure.

**ChanSpy audio fix (post-test fix)** — discovered during demo
testing that the `o` flag in our ChanSpy options blocked Gemini's
voice from reaching the supervisor (only the caller was audible).
Dropped `o` from all three modes (listen / whisper / barge) and now
both directions are captured correctly. Lives in
`backend/app/demos/clinic/ami.py` — travels via git, no per-machine
action.

**WhatsApp via WasenderApi (new feature)** — full inbox under Call
Center → WhatsApp. Two-pane layout: chat list (left) + active
conversation with chat-bubbles + send form (right). Chats poll every
15s, open conversation every 5s. Sending hits WasenderApi's
`/api/send-message`; listing uses `/api/whatsapp-sessions/{id}/message-logs`
grouped client-side by `remoteJid`. Status pill at the top confirms
"Connected · N contacts" or surfaces the WasenderApi error. **Two
per-machine config fields** (API key + session ID) live in the same
Configuration page as AMI — see Step 3.

**Tool hardening** — Saudi phone numbers auto-normalised to E.164
(`+9665XXXXXXXX`). `create_appointment` / `reschedule_appointment`
hard-reject off-grid slot times.

---

## Step 1 — pull both repos `[code]`

You have two repos:

```
~/Documents/New Projects 2026/
├── PWDemoMaster/        (or pw-demo-master/ on machine A)
└── prime-mate-clinic/   (or lovable-clinic/ on machine A)
```

**Git Bash** (recommended, works on both Win + Mac):

```bash
export PW_ROOT="$HOME/Documents/New Projects 2026"   # adjust if different

for repo in PWDemoMaster prime-mate-clinic; do
  echo "=== $repo ==="
  (cd "$PW_ROOT/$repo" && git status --short --branch && git pull --ff-only)
done
```

**PowerShell:**

```powershell
$env:PW_ROOT = "$env:USERPROFILE\Documents\New Projects 2026"
foreach ($repo in "PWDemoMaster", "prime-mate-clinic") {
  Write-Host "=== $repo ==="
  Push-Location "$env:PW_ROOT\$repo" -ErrorAction Stop
  git status --short --branch
  git pull --ff-only
  Pop-Location
}
```

If `git pull --ff-only` refuses to fast-forward (local diverging
commits), see DEMOSITEMAP.md §"Switching to Machine A" for the safe
recovery procedure.

The pulled changes include:

- Backend persona/tool/echo-gate fixes
- New `backend/app/demos/clinic/ami.py` (asyncio AMI client)
- New REST endpoints for escalation + dial-in
- Frontend changes already built into `frontend/demos/clinic/`
- Updated `DEMOSITEMAP.md` (§6c, §6d)

**No `npm install` required** unless `package.json` actually changed
(check `git diff HEAD@{1} -- prime-mate-clinic/package.json`). The
deployed SPA bundle in `frontend/demos/clinic/` came along with the
pull, no rebuild needed.

---

## Step 2 — one-time PBX setup `[per-PBX]`

**Skip this entire step if both machines talk to the SAME FreePBX.**

If the office uses a different PBX, do all three:

### 2a. AMI bind address — `0.0.0.0` (FreePBX 16+ defaults to localhost)

FreePBX UI:
- **Settings → Advanced Settings**
- Top-right: *Display Readonly Settings* = **Yes**, *Override Readonly Settings* = **Yes**
- Filter for `AMI`
- **AMI bind address** → `0.0.0.0`
- Submit → red **Apply Config** bar

Or SSH:
```bash
nano /etc/asterisk/manager.conf
# In [general], set bindaddr = 0.0.0.0
/usr/sbin/asterisk -rx "manager reload"
```

Verify from the backend host: `Test-NetConnection <pbx-ip> -Port 5038`
must return `TcpTestSucceeded : True`.

### 2b. Manager user — `pwdemo-clinic`

**Admin → Asterisk Manager Users → Add Manager**

| Field | Value |
| --- | --- |
| User Name | `pwdemo-clinic` |
| Secret | strong (40+ char hex); generate fresh per PBX |
| Deny | `0.0.0.0/0.0.0.0` |
| Permit | `192.168.100.0/255.255.255.0` (or the office subnet — **NOT** `0.0.0.0/255.255.255.0`, that means "the 0.0.0.0/24 network", not "everyone") |
| Read | `system, call, log, verbose, agent, user, config, command, dtmf, reporting, cdr, dialplan, originate, message` |
| Write | same set |

Submit → Apply Config.

Verify auth from the backend host:
```bash
echo -e "Action: Login\r\nUsername: pwdemo-clinic\r\nSecret: <secret>\r\n\r\nAction: Logoff\r\n\r\n" | nc <pbx-ip> 5038
```

You want `Response: Success`. If `Authentication failed`:
- `tail -f /var/log/asterisk/full | grep -i manager` on the PBX while retrying
- `failed to pass IP ACL` → Permit IP doesn't match — fix the netmask
- `failed to authenticate` (no ACL line) → wrong secret

### 2c. Dialplan refactor — Local pair so ChanSpy can hear both directions

SSH into PBX:
```bash
nano /etc/asterisk/extensions_custom.conf
```

Make `[pwdemo-clinic-agent]` look like this (replace `192.168.100.25`
with your backend host's LAN IP):

```ini
[pwdemo-clinic-agent]
exten => s,1,NoOp(Clinic Live Agent — Layla)
 same => n,Answer()
 same => n,Wait(0.3)
 same => n,Set(AUDIOSOCKET_UUID=33333333-3333-3333-3333-333333333333)
 ; Caller is bridged with a Local/* channel — ChanSpy works on bridges.
 same => n,Dial(Local/${AUDIOSOCKET_UUID}@pwdemo-clinic-audiosocket/n)
 same => n,Hangup()

[pwdemo-clinic-audiosocket]
exten => _.,1,NoOp(AudioSocket leg for ${EXTEN})
 same => n,Answer()
 same => n,AudioSocket(${EXTEN},192.168.100.25:8092)
 same => n,Hangup()
```

Reload:
```bash
/usr/sbin/asterisk -rx "dialplan reload"
```

Verify both contexts exist:
```bash
grep -A 4 "pwdemo-clinic-agent\|pwdemo-clinic-audiosocket" /etc/asterisk/extensions_custom.conf
```

---

## Step 3 — per-machine Configuration page `[per-machine]`

`data/demos/clinic/escalation.json` is **gitignored** — every credential
in it must be re-entered via the UI on each machine. One page, three
sub-sections.

1. Open the demo: `/demo/clinic/call-center/configuration`
2. Log in: `demo / demo`
3. Scroll to **Supervisor escalation triggers** (last card on the page)

### 3a. Supervisor dial-in (escalation + AMI)

Fill:
- **Supervisor extension** — the PBX extension to ring on flag (e.g. `1003`)
- **PBX integration (AMI)** subsection:
  - AMI host = your PBX LAN IP (e.g. `192.168.100.23`)
  - AMI port = `5038`
  - AMI username = `pwdemo-clinic`
  - AMI secret = (the 40-char value you set in step 2b)

### 3b. WhatsApp (WasenderApi)

In the same card, **WhatsApp (WasenderApi)** dashed subsection — fill
both fields:

- **WhatsApp API key** — the per-session API key from the WasenderApi
  dashboard (the key beside your paired WhatsApp number)
- **WhatsApp session ID** — find it on the same dashboard under your
  paired number. Sending works without this; the inbox (chat list +
  message history) doesn't.

Then **Save** (top-right of the card) — message reads
*"Saved — takes effect on the next call"*. No restart needed.

### Getting the values from machine A

Same PBX + same WasenderApi number = same values. Lift them off
machine A's gitignored file:

```bash
# On machine A, in PWDemoMaster:
python -c "
import json
d = json.load(open('data/demos/clinic/escalation.json'))
for k in ('ami_secret', 'ami_host', 'ami_username',
          'supervisor_extension',
          'wasender_api_key', 'wasender_session_id'):
    print(f'{k}: {d.get(k, \"\")!r}')
"
```

Paste each value into the matching field on machine B's Configuration
page. The API key and AMI secret are masked once entered.

Different WasenderApi account on the office machine → generate a new
API key + session ID on that account's dashboard and use those instead.

---

## Step 4 — restart the backend

```powershell
# Stop the old uvicorn (Ctrl+C in its window, or:)
Get-Process python | Where-Object {$_.Path -like "*\.venv\*"} | Stop-Process

# Start fresh
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

(Adjust port to whatever you use.)

Watch the startup log for:
- `SIP Live Agent bind succeeded on 0.0.0.0:8090`
- `SIP Live Rep bind succeeded on 0.0.0.0:8091`
- `Clinic Live Agent bind succeeded on 0.0.0.0:8092`

If you see `Errno 10048: only one usage of each socket address`, an
old python process is still holding the ports — `Stop-Process` it.

---

## Step 5 — verify end-to-end

1. **Open the SPA**: `/demo/clinic/call-center/dashboard`
2. **Call extension 9001** from your PBX softphone — say "hello" so a
   call row appears on the Dashboard
3. **Confirm the row tints yellow** (caller not yet identified) → say
   your name/file number → row should flip green
4. **Test escalation**: say "I want to speak to the manager" → the row
   should paint red within a second, with an Acknowledge button + the
   3 dial buttons. Click Acknowledge → red clears.
5. **Test dial-in (Listen mode first)**:
   - Click **👂 Listen** on the row
   - Your softphone at the configured supervisor extension should ring
   - Pick up → you should hear both the caller AND the agent (Gemini)
   - Hang up → you exit, the call continues

If you hear only the caller, ChanSpy isn't capturing the write
direction — verify Step 2c (Local-pair dialplan) and that you
reloaded `dialplan reload`. Tail uvicorn during the click; the line
`clinic dial_supervisor: ... style=...` tells you which channel was
spied on (should be `style=local-pair-bridge-peer`, target should be a
`PJSIP/…` channel).

6. **Test Whisper / Barge** the same way:
   - Whisper: only the caller hears you, the AI keeps talking unaware
   - Barge: both the caller AND the AI hear you (3-way)
7. **WhatsApp — send a message**:
   - Open **Call Center → WhatsApp** (under the Call Center group)
   - Top-right pill should read **🟢 Connected · N contacts**. If it
     reads **🟡 Not configured** → step 3b wasn't saved. If it reads
     **🔴 Error** → hover the pill, the tooltip carries the WasenderApi
     error (usually expired key or session offline — re-scan on the
     dashboard).
   - **Quick send test:** in the chat list (left), pick any conversation
     OR if the list is empty open one chat on your phone first so
     there's at least one. Click that row, type a short message in the
     box at the bottom, press **Enter**. Message lands within a few
     seconds; the open conversation refreshes immediately.
8. **WhatsApp — inbox refresh**:
   - Send yourself a message from another phone to your paired
     WhatsApp number while the page is open.
   - Within ~15 seconds the chat list refreshes (new conversation
     appears at top) and within ~5s of selecting that chat the new
     message renders as a left-aligned bubble.

---

## Step 6 — sanity-check the persona changes

Make a fresh call and verify the persona behaves:

- [ ] Agent doesn't ask about your gender (infers from voice)
- [ ] Agent reads digits one at a time when telling you a file number / appointment ID / phone
- [ ] Agent uses the correct date when you say "tomorrow"
- [ ] Agent only offers slot times that match the clinic's 30-min grid (09:00 / 09:30 / etc., never 09:17)
- [ ] If you say "I want a manager" → row flags red on the Dashboard within ~1s
- [ ] After ack + saying it again → row flags red AGAIN (no longer silently swallowed)
- [ ] Mobile entered as `0501234567` saves as `+966501234567` in Patients

If any of these regress, ping me with the call_id and what the agent
said vs. what it should have said.

---

## What's NOT in this checklist (because it travels via git)

You don't need to do anything for these — they came down with the pull:

**Live Agent / supervisor escalation:**
- All persona/guardrail text in `_GUARDRAILS` and `_build_system_instruction`
- The `flag_for_supervisor` tool definition + handler
- The slot-grid enforcement in `_t_create_appointment` / `_t_reschedule_appointment`
- The `_format_saudi_mobile` helper
- The whole new `ami.py` file + ChanSpy `o`-flag fix (Listen/Whisper/Barge audio works both directions)
- The new REST endpoints (`/agent/escalation`, `/agent/calls/{id}/acknowledge_flag`, `/agent/calls/{id}/dial_supervisor`)
- The frontend `LiveCallsTable` / `FlagBanner` / `DialModeButtons` components
- The frontend `EscalationConfigCard` on the Configuration page (now includes the WhatsApp section)
- The transcript garbage filter (`looksLikeGarbage`)
- The DEMOSITEMAP.md §6c + §6d reference docs

**WhatsApp (WasenderApi):**
- The whole new `backend/app/demos/clinic/wasender.py` httpx wrapper
- The new REST endpoints (`/whatsapp/status`, `/whatsapp/send`, `/whatsapp/chats`, `/whatsapp/messages`)
- The new sidebar entry under Call Center → **💬 WhatsApp** (`MessageCircle` icon)
- The new frontend route `_app.call-center.whatsapp.tsx` (two-pane inbox: chat list + message thread + send form, with chat polling at 15s and open-conversation polling at 5s)
- The new `whatsapp` i18n key (en + ar)
- The `wasender_api_key` + `wasender_session_id` fields added to `DEFAULT_ESCALATION` defaults — empty until filled via Configuration

---

## Reference (after pull)

- **Feature deep-dive** → `DEMOSITEMAP.md` §6c (supervisor escalation + dial-in) and §6d (persona + tool hardening)
- **AMI client code** → `backend/app/demos/clinic/ami.py`
- **WasenderApi wrapper** → `backend/app/demos/clinic/wasender.py`
- **REST routes** → `backend/app/demos/clinic/router.py` (search `whatsapp` / `escalation` / `dial_supervisor`)
- **Persona / guardrails / escalation config** → `backend/app/demos/clinic/live_agent.py` (search `_GUARDRAILS`, `DEFAULT_ESCALATION`, `_build_system_instruction`)
- **Tool implementations** → `backend/app/demos/clinic/agent_tools.py` (search `_t_flag_for_supervisor`, `_format_saudi_mobile`)
- **Dashboard table + buttons** → `prime-mate-clinic/src/routes/_app.call-center.dashboard.tsx`
- **WhatsApp page** → `prime-mate-clinic/src/routes/_app.call-center.whatsapp.tsx`
- **Configuration page editor** (AMI + WhatsApp) → `prime-mate-clinic/src/routes/_app.call-center.configuration.tsx`
- **Sidebar** → `prime-mate-clinic/src/components/AppSidebar.tsx`

---

## If anything breaks

1. Tail uvicorn — look for tracebacks or `AMI`/`escalation`/`wasender` warnings
2. On the PBX: `tail -f /var/log/asterisk/full | grep -iE "manager|originate|chanspy"` while clicking a button
3. From the SPA: `curl http://localhost:8000/api/demo/clinic/agent/escalation` → confirm all keys non-empty (`ami_host`, `ami_username`, `ami_secret`, `supervisor_extension`, `wasender_api_key`, `wasender_session_id`)

Most likely failure modes and their tells:

**Supervisor dial-in:**

| Symptom | Likely cause |
| --- | --- |
| Button does nothing, console shows `Auto-dial failed: connect to … failed` | AMI host unreachable — wrong IP or AMI still bound to `127.0.0.1` |
| Button says `Auto-dial failed: AMI login: Authentication failed` | Username/secret wrong OR Permit IP doesn't include this backend |
| Button says `Auto-dial failed: HTTP 404` | uvicorn not restarted — old code |
| Phone rings, beep, hang up | No active AudioSocket channel found — make sure a call is actually live on extension 9001 |
| Phone rings, you join, but you hear only the caller | Dialplan refactor (Step 2c) not applied OR not reloaded |

**WhatsApp:**

| Symptom | Likely cause |
| --- | --- |
| Status pill reads **🟡 Not configured** | API key field empty in Configuration → step 3b not saved |
| Status pill reads **🔴 Error** with tooltip `Unauthorized` / `Invalid API key` | Wrong API key — re-copy from WasenderApi dashboard |
| Status pill reads **🔴 Error** with `Session offline` / `Disconnected` | Paired WhatsApp session dropped — re-scan QR on the WasenderApi dashboard |
| Chats list is empty even though pill is green | (a) No conversations on this number yet (legitimate empty state), or (b) `wasender_session_id` empty/wrong — check `GET /whatsapp/chats` response in DevTools, the `error` field tells you which |
| Send returns OK but conversation doesn't refresh | 5-second poll hasn't ticked yet OR the click hit the wrong `selectedJid` — click the chat again |
| Messages render as `[text]` / `[image]` literal | Backend `_msg_text` helper didn't match the WasenderApi response shape — paste me one raw row from `GET /whatsapp-sessions/{id}/message-logs?limit=1` and I'll tighten the field mapping |

**General:**

| Symptom | Likely cause |
| --- | --- |
| Configuration page section missing | SPA bundle stale — confirm `git pull` brought in `frontend/demos/clinic/index.html` with a fresh hash |
| Sidebar WhatsApp entry missing | Same — SPA bundle didn't update; do `git diff HEAD@{1} -- frontend/demos/clinic/index.html` to confirm a new hash landed |
| 500 errors on any new endpoint | uvicorn wasn't restarted after the pull — the new `wasender.py` / `ami.py` modules didn't load |
