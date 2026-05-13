// =============================================================
// Smart Home · Live Agent — browser side
//
// Default flow:
//   1. Click "Start Session" → opens WebSocket to backend, starts mic level
//      meter, starts browser SpeechRecognition.
//   2. Speak — text fills the input box live; finalized phrases auto-send
//      to the agent.
//   3. "Mute" pauses sending (but leaves the meter / STT listening for a
//      wake word).
//   4. Optional wake/stop words let you toggle mute by voice.
//
// Note: this file no longer uses the raw-audio worklet path. Gemini Live's
// audio-in route was unreliable across machines, so we use browser STT
// for input and play the agent's audio response on output (PCM 24 kHz).
// =============================================================

const LIVE = {
  ws: null,
  active: false,

  // Mic meter (independent getUserMedia stream so it's not tied to STT)
  meterCtx: null,
  meterStream: null,
  meterSource: null,
  meterAnalyser: null,
  meterRaf: null,

  // Speech-to-text
  stt: null,
  sttRestartTimer: null,
  sttMuted: false,
  sttLastSent: '',

  // Wake words
  wakeWord: '',
  stopWord: '',

  // Agent filters
  onlyAreas: false,

  // Audio playback (agent voice)
  outCtx: null,
  outNextStart: 0,
  echoing: false,       // true while agent's voice is being played (mic is suppressed)
  echoEndTimer: null,

  // Camera frame streaming
  cameraTimer: null,
  cameraName: null,

  // True once a mic stream has been acquired this session. Stays false when
  // the machine has no input device — session continues in text-only mode.
  hasMic: false,

  log: null,
};

// =============================================================
// Helpers
// =============================================================
function base64FromArrayBuffer(buf) {
  const bytes = new Uint8Array(buf);
  let s = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(s);
}

function int16ArrayFromBase64(b64) {
  const bin = atob(b64);
  const buf = new ArrayBuffer(bin.length);
  const view = new Uint8Array(buf);
  for (let i = 0; i < bin.length; i++) view[i] = bin.charCodeAt(i);
  return new Int16Array(buf);
}

function logLine(kind, text) {
  if (!LIVE.log) return;
  const line = document.createElement('div');
  line.className = `log-line${kind ? ' ' + kind : ''}`;
  line.textContent = `[${new Date().toLocaleTimeString()}] ${text}`;
  LIVE.log.prepend(line);
}

// Streamed channels (agent/user transcripts) arrive as many small chunks
// per turn. To avoid one log row per chunk, we keep a single "open" line
// per stream id and append text into it until the turn closes.
//
// Call appendStream('agent_text', kind, prefix, chunk) to append; call
// closeStreams() on turn_complete / interrupted to start fresh next turn.
const STREAM_LINES = {};
function appendStream(id, kind, prefix, chunk) {
  if (!LIVE.log || !chunk) return;
  let entry = STREAM_LINES[id];
  if (!entry) {
    const el = document.createElement('div');
    el.className = `log-line${kind ? ' ' + kind : ''}`;
    const ts = new Date().toLocaleTimeString();
    el.textContent = `[${ts}] ${prefix}${chunk}`;
    LIVE.log.prepend(el);
    STREAM_LINES[id] = { el, text: chunk, ts, prefix };
  } else {
    entry.text += chunk;
    entry.el.textContent = `[${entry.ts}] ${entry.prefix}${entry.text}`;
  }
}
function closeStreams() {
  for (const k of Object.keys(STREAM_LINES)) delete STREAM_LINES[k];
}

function setLiveStatus(state, text) {
  const dot = document.getElementById('live-dot');
  const txt = document.getElementById('live-status-text');
  if (dot) {
    dot.classList.remove('ok', 'err', 'warn', 'checking');
    if (state !== 'idle') dot.classList.add(state);
  }
  if (txt) txt.textContent = text;
}

// =============================================================
// Mic level meter (uses its own getUserMedia stream so it always runs
// while the session is active, even while muted).
// =============================================================
async function startMeter() {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  LIVE.meterCtx = new Ctx();
  if (LIVE.meterCtx.state === 'suspended') {
    try { await LIVE.meterCtx.resume(); } catch {}
  }

  LIVE.meterStream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    video: false,
  });

  LIVE.meterSource = LIVE.meterCtx.createMediaStreamSource(LIVE.meterStream);
  LIVE.meterAnalyser = LIVE.meterCtx.createAnalyser();
  LIVE.meterAnalyser.fftSize = 256;
  LIVE.meterAnalyser.smoothingTimeConstant = 0.2;
  LIVE.meterSource.connect(LIVE.meterAnalyser);
  // No connection to destination — meter only.

  startLevelMonitor();
}

function startLevelMonitor() {
  if (!LIVE.meterAnalyser) return;
  const buf = new Uint8Array(LIVE.meterAnalyser.fftSize);
  let peakHold = 0;
  let peakDecayAt = 0;
  const tick = () => {
    if (!LIVE.meterAnalyser) return;
    LIVE.meterAnalyser.getByteTimeDomainData(buf);
    let peak = 0;
    for (let i = 0; i < buf.length; i++) {
      const v = Math.abs(buf[i] - 128);
      if (v > peak) peak = v;
    }
    const level = peak / 128;
    const now = performance.now();
    if (level >= peakHold || now > peakDecayAt) {
      peakHold = level;
      peakDecayAt = now + 400;
    }
    updateMeterUI(level, peakHold);
    LIVE.meterRaf = requestAnimationFrame(tick);
  };
  LIVE.meterRaf = requestAnimationFrame(tick);
}

function updateMeterUI(level, peak) {
  const bar = document.getElementById('mic-meter-bar');
  const peakEl = document.getElementById('mic-meter-peak');
  if (bar) bar.style.width = `${Math.min(100, level * 140).toFixed(1)}%`;
  if (peakEl) peakEl.style.left = `${Math.min(100, peak * 140).toFixed(1)}%`;
}

function stopMeter() {
  if (LIVE.meterRaf) cancelAnimationFrame(LIVE.meterRaf);
  LIVE.meterRaf = null;
  updateMeterUI(0, 0);
  try { LIVE.meterAnalyser?.disconnect(); } catch {}
  try { LIVE.meterSource?.disconnect(); } catch {}
  try { LIVE.meterStream?.getTracks().forEach((t) => t.stop()); } catch {}
  try { LIVE.meterCtx?.close(); } catch {}
  LIVE.meterAnalyser = null;
  LIVE.meterSource = null;
  LIVE.meterStream = null;
  LIVE.meterCtx = null;
}

// =============================================================
// Audio playback (agent voice — PCM 24 kHz from backend)
// =============================================================
function ensureOutCtx() {
  if (!LIVE.outCtx) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    LIVE.outCtx = new Ctx({ sampleRate: 24000 });
    LIVE.outNextStart = LIVE.outCtx.currentTime;
  }
  return LIVE.outCtx;
}

function playPcm24k(int16) {
  const ctx = ensureOutCtx();
  const f32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) f32[i] = int16[i] / 0x8000;
  const buf = ctx.createBuffer(1, f32.length, 24000);
  buf.copyToChannel(f32, 0);
  const src = ctx.createBufferSource();
  src.buffer = buf;
  src.connect(ctx.destination);
  const startAt = Math.max(ctx.currentTime, LIVE.outNextStart);
  src.start(startAt);
  LIVE.outNextStart = startAt + buf.duration;
}

function flushPlayback() {
  if (LIVE.outCtx) LIVE.outNextStart = LIVE.outCtx.currentTime;
}

// =============================================================
// Echo gate — half-duplex: while the agent is speaking, suppress STT so
// the mic doesn't pick up the agent's own voice from the speakers.
// =============================================================
function beginEcho() {
  // Cancel any pending end-of-echo so further audio extends the gate.
  if (LIVE.echoEndTimer) { clearTimeout(LIVE.echoEndTimer); LIVE.echoEndTimer = null; }
  if (!LIVE.echoing) {
    LIVE.echoing = true;
    // Abort the recognizer so anything it picked up just-before-now is dropped.
    try { LIVE.stt?.abort(); } catch {}
    setLiveStatus('checking', 'Agent speaking…');
  }
}

function scheduleEchoEnd() {
  if (LIVE.echoEndTimer) { clearTimeout(LIVE.echoEndTimer); LIVE.echoEndTimer = null; }
  if (!LIVE.echoing) return;
  // Wait until the queued audio has finished playing, plus a small grace
  // window for room reverberation to die down.
  const remainingMs = LIVE.outCtx
    ? Math.max(0, (LIVE.outNextStart - LIVE.outCtx.currentTime) * 1000)
    : 0;
  LIVE.echoEndTimer = setTimeout(() => {
    LIVE.echoing = false;
    LIVE.echoEndTimer = null;
    setLiveStatus('ok', 'Listening');
    // Restart the recognizer if the session is still going and not user-muted.
    if (LIVE.active && LIVE.stt) {
      try { LIVE.stt.start(); } catch {}
    }
  }, remainingMs + 250);
}

// =============================================================
// Speech-to-Text (browser-side via SpeechRecognition).
// While the session is active STT is *always running*; the `sttMuted`
// flag controls whether finalized text gets sent to the agent. Wake/stop
// words flip that flag.
// =============================================================
function sttSupported() {
  return typeof window.SpeechRecognition !== 'undefined' || typeof window.webkitSpeechRecognition !== 'undefined';
}

function startSTT() {
  if (!sttSupported()) {
    logLine('err', 'SpeechRecognition not supported in this browser. Try Chrome.');
    return false;
  }
  const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
  LIVE.stt = new Rec();
  LIVE.stt.continuous = true;
  LIVE.stt.interimResults = true;
  LIVE.stt.lang = navigator.language || 'en-US';
  LIVE.sttLastSent = '';

  const input = () => document.getElementById('live-text-input');

  LIVE.stt.onresult = (event) => {
    // Drop anything the recognizer produces while the agent is speaking —
    // it would otherwise feed the agent's own voice back as the user's turn.
    if (LIVE.echoing) {
      try { LIVE.stt.abort(); } catch {}
      return;
    }

    let interim = '';
    let final = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const r = event.results[i];
      if (r.isFinal) final += r[0].transcript;
      else interim += r[0].transcript;
    }
    const live = (final + interim).trim();
    const lower = live.toLowerCase();

    // ----- Wake / stop word detection (always-on) -----------------------
    if (LIVE.wakeWord && LIVE.sttMuted && lower.includes(LIVE.wakeWord)) {
      setMuted(false);
      logLine('ok', `🔔 Wake word "${LIVE.wakeWord}" heard — listening.`);
      // Reset the recognizer so the wake phrase isn't sent as a message.
      try { LIVE.stt.abort(); } catch {}
      // onend will auto-restart.
      const el = input(); if (el) el.value = '';
      return;
    }
    if (LIVE.stopWord && !LIVE.sttMuted && lower.includes(LIVE.stopWord)) {
      setMuted(true);
      logLine('ok', `🔕 Stop word "${LIVE.stopWord}" heard — muted.`);
      try { LIVE.stt.abort(); } catch {}
      const el = input(); if (el) el.value = '';
      return;
    }

    // ----- Show what's being heard --------------------------------------
    const el = input();
    if (el) el.value = live;

    // ----- Auto-send finalized phrases when not muted -------------------
    if (LIVE.sttMuted) return;
    if (final) {
      const text = final.trim();
      if (text && text !== LIVE.sttLastSent) {
        LIVE.sttLastSent = text;
        sendText(text);
        if (el) el.value = '';
      }
    }
  };

  LIVE.stt.onerror = (e) => {
    const err = e.error || e.message || '';
    if (err === 'no-speech' || err === 'aborted') return; // benign
    logLine('err', `stt error: ${err}`);
  };

  LIVE.stt.onend = () => {
    // Don't auto-restart while the agent is speaking — the echo-end timer
    // will kick STT back to life once playback has fully drained.
    if (!LIVE.active || LIVE.echoing) return;
    clearTimeout(LIVE.sttRestartTimer);
    LIVE.sttRestartTimer = setTimeout(() => {
      if (!LIVE.active || !LIVE.stt || LIVE.echoing) return;
      try { LIVE.stt.start(); } catch {}
    }, 250);
  };

  try {
    LIVE.stt.start();
    return true;
  } catch (e) {
    logLine('err', `failed to start STT: ${e.message}`);
    return false;
  }
}

function stopSTT() {
  clearTimeout(LIVE.sttRestartTimer);
  LIVE.sttRestartTimer = null;
  try { LIVE.stt?.abort(); } catch {}
  LIVE.stt = null;
}

function setMuted(mute) {
  LIVE.sttMuted = !!mute;
  const btn = document.getElementById('btn-mute');
  if (btn) {
    btn.classList.toggle('active', !!mute);
    btn.textContent = mute ? '🔇 Muted' : '🎤 Listening';
  }
  const input = document.getElementById('live-text-input');
  if (input && mute) input.value = '';
}

// =============================================================
// Camera frame streaming (unchanged behavior)
// =============================================================
function startCameraStreaming(cameraName) {
  stopCameraStreaming();
  LIVE.cameraName = cameraName;
  if (!cameraName) return;
  LIVE.cameraTimer = setInterval(() => sendCameraFrame(cameraName), 1500);
  sendCameraFrame(cameraName);
}

function stopCameraStreaming() {
  if (LIVE.cameraTimer) clearInterval(LIVE.cameraTimer);
  LIVE.cameraTimer = null;
  LIVE.cameraName = null;
}

async function sendCameraFrame(cameraName) {
  if (!LIVE.ws || LIVE.ws.readyState !== WebSocket.OPEN) return;
  try {
    const res = await fetch(`/api/frigate/snapshot/${encodeURIComponent(cameraName)}?h=480&cb=${Date.now()}`);
    if (!res.ok) return;
    const blob = await res.blob();
    const b64 = await blobToBase64(blob);
    LIVE.ws.send(JSON.stringify({ type: 'video', mime: blob.type || 'image/jpeg', data: b64 }));
  } catch { /* ignore transient errors */ }
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onloadend = () => {
      const result = r.result || '';
      const comma = result.indexOf(',');
      resolve(comma >= 0 ? result.slice(comma + 1) : '');
    };
    r.onerror = reject;
    r.readAsDataURL(blob);
  });
}

// =============================================================
// WebSocket lifecycle
// =============================================================
function openWebSocket() {
  return new Promise((resolve, reject) => {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${location.host}/api/live-agent/ws`;
    const ws = new WebSocket(url);
    LIVE.ws = ws;
    let settled = false;

    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      // Resolve on the first 'ready' / fail on first 'error'.
      if (!settled) {
        if (msg.type === 'ready') {
          settled = true;
          setLiveStatus('ok', `Ready · ${msg.model}`);
          resolve();
        } else if (msg.type === 'error') {
          settled = true;
          setLiveStatus('err', msg.message || 'Error');
          reject(new Error(msg.message || 'Live agent error'));
          try { ws.close(); } catch {}
          return;
        }
      }
      handleServerMessage(msg);
    };
    ws.onopen = () => setLiveStatus('checking', 'Connecting…');
    ws.onerror = () => {
      if (!settled) reject(new Error('WebSocket error'));
      setLiveStatus('err', 'WebSocket error');
    };
    ws.onclose = (ev) => {
      setLiveStatus('idle', ev.wasClean ? 'Disconnected' : `Closed (${ev.code})`);
      // Tear down session-level resources on unexpected close.
      cleanup();
    };
  });
}

function handleServerMessage(msg) {
  switch (msg.type) {
    case 'audio': {
      const int16 = int16ArrayFromBase64(msg.data);
      // Suppress STT before queuing audio so we never race the first frame.
      beginEcho();
      playPcm24k(int16);
      break;
    }
    case 'turn_complete':
      // No more audio incoming for this turn — schedule the echo gate to lift
      // once the queued audio has finished playing, and close any streamed
      // transcript lines so the next turn starts on a fresh row.
      closeStreams();
      scheduleEchoEnd();
      break;
    case 'text':
      appendStream('text', 'agent', 'agent: ', msg.text);
      break;
    case 'user_text':
      appendStream('user_text', 'you', '(heard) ', msg.text);
      break;
    case 'agent_text':
      appendStream('agent_text', 'agent', '(spoken) ', msg.text);
      break;
    case 'tool_call':
      // Tool activity is a hard turn boundary in our log.
      closeStreams();
      logLine('tool', `→ ${msg.name}(${JSON.stringify(msg.args)})`);
      break;
    case 'tool_result':
      logLine('tool', `← ${msg.name}: ${JSON.stringify(msg.result).slice(0, 400)}`);
      break;
    case 'interrupted':
      closeStreams();
      flushPlayback();
      scheduleEchoEnd();
      break;
    case 'config_ack':
      if (msg.only_areas) {
        logLine('ok', `Only-Areas filter ON · ${msg.area_entity_count} entities exposed to the agent.`);
      } else {
        logLine('ok', `Only-Areas filter OFF · all entities exposed to the agent.`);
      }
      break;
    case 'error':
      logLine('err', `error: ${msg.message}`);
      setLiveStatus('err', msg.message);
      break;
  }
}

function sendText(text) {
  if (!LIVE.ws || LIVE.ws.readyState !== WebSocket.OPEN) return;
  LIVE.ws.send(JSON.stringify({ type: 'text', text }));
  logLine('you', `you: ${text}`);
}

function sendConfig(patch) {
  if (!LIVE.ws || LIVE.ws.readyState !== WebSocket.OPEN) return;
  LIVE.ws.send(JSON.stringify({ type: 'config', ...patch }));
}

function setOnlyAreas(on) {
  LIVE.onlyAreas = !!on;
  // If a session is active, push the change immediately.
  if (LIVE.ws && LIVE.ws.readyState === WebSocket.OPEN) {
    sendConfig({ only_areas: !!on });
  }
}

// =============================================================
// Session lifecycle
// =============================================================
async function startSession({ camera, log, wakeWord, stopWord, onlyAreas }) {
  LIVE.log = log;
  LIVE.wakeWord = (wakeWord || '').toLowerCase().trim();
  LIVE.stopWord = (stopWord || '').toLowerCase().trim();
  LIVE.onlyAreas = !!onlyAreas;
  LIVE.active = true;
  // If a wake word is configured, start muted (waits for the wake phrase).
  // Otherwise listen immediately.
  LIVE.sttMuted = !!LIVE.wakeWord;

  try {
    await openWebSocket();
    // Push initial agent-side config to the backend so the filter applies
    // to the very first tool call.
    sendConfig({ only_areas: LIVE.onlyAreas });

    // Mic + STT are optional: if no input device is present (or the user
    // denies permission), keep the session alive and let the text input
    // drive the conversation instead.
    let sttOk = false;
    try {
      await startMeter();
      LIVE.hasMic = true;
      sttOk = startSTT();
    } catch (e) {
      LIVE.hasMic = false;
      logLine('err', `No microphone (${e.message || e.name || 'unavailable'}) — continuing in text-only mode.`);
    }

    if (camera) startCameraStreaming(camera);

    // Without a mic, mute/wake-word logic doesn't apply — force-mute so any
    // stray STT plumbing stays inert, and reflect that in the UI.
    if (!LIVE.hasMic) LIVE.sttMuted = true;
    setMuted(LIVE.sttMuted);

    if (sttOk) {
      const prefix = LIVE.wakeWord ? `Say "${LIVE.wakeWord}" to start, "${LIVE.stopWord || '(no stop word)'}" to mute. ` : 'Listening — speak naturally. ';
      logLine('ok', `Session started. ${prefix}`);
    } else if (LIVE.hasMic) {
      logLine('ok', `Session started. Type below to chat (browser STT unavailable).`);
    } else {
      logLine('ok', `Session started · text-only. Type below and press Enter to chat.`);
    }
  } catch (e) {
    logLine('err', `start failed: ${e.message}`);
    cleanup();
    throw e;
  }
}

function stopSession() {
  LIVE.active = false;
  if (LIVE.ws && LIVE.ws.readyState === WebSocket.OPEN) {
    try { LIVE.ws.close(); } catch {}
  }
  cleanup();
}

function cleanup() {
  LIVE.active = false;
  LIVE.hasMic = false;
  if (LIVE.echoEndTimer) { clearTimeout(LIVE.echoEndTimer); LIVE.echoEndTimer = null; }
  LIVE.echoing = false;
  closeStreams();
  stopSTT();
  stopMeter();
  stopCameraStreaming();
  if (LIVE.outCtx) {
    try { LIVE.outCtx.close(); } catch {}
    LIVE.outCtx = null;
  }
  // Reset UI buttons.
  const startBtn = document.getElementById('btn-live-start');
  const stopBtn  = document.getElementById('btn-live-stop');
  const muteBtn  = document.getElementById('btn-mute');
  if (startBtn) startBtn.disabled = false;
  if (stopBtn)  stopBtn.disabled  = true;
  if (muteBtn)  {
    muteBtn.disabled = true;
    muteBtn.classList.remove('active');
    muteBtn.textContent = '🎤 Listening';
  }
}

// =============================================================
// Public API used by app.js
// =============================================================
window.LiveAgentSession = {
  start: startSession,
  stop:  stopSession,
  setCamera: (name) => {
    if (LIVE.active) startCameraStreaming(name);
    else LIVE.cameraName = name;
  },
  sendText,
  setMuted,
  setOnlyAreas,
  isActive:    () => LIVE.active,
  isMuted:     () => LIVE.sttMuted,
  isOnlyAreas: () => LIVE.onlyAreas,
  hasMic:      () => LIVE.hasMic,
};
