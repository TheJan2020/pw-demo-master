// =============================================================
// SIP Phone — browser-side softphone built on JsSIP.
//
// JsSIP runs entirely in this page. We connect to the PBX over SIP-over-
// WebSocket (ws:// or wss://) and carry audio through WebRTC. The backend
// only supplies stored credentials; no SIP/RTP traffic flows through it.
//
// Lifetime:
//   - The UA is created and started by `startPhone(config)` when the
//     Extension page mounts (or when the user hits "Register").
//   - One UA per browser tab; multiple tabs would try to register the
//     same extension and conflict with the PBX.
//   - `stopPhone()` unregisters and disposes everything.
//
// All UI state changes fan out via the `phoneEvent` callback so the page
// can stay declarative.
// =============================================================

(function () {
  const PHONE = {
    ua: null,
    activeSession: null,
    incomingSession: null,
    callStartedAt: null,
    history: [],          // {ts, direction:'in'|'out', peer, status:'completed'|'missed'|'failed', duration_s}
    listeners: new Set(),
    config: null,
    audioEl: null,        // <audio autoplay> for remote stream
  };

  // ---------- helpers --------------------------------------------------

  function emit(event) {
    for (const cb of PHONE.listeners) {
      try { cb(event); } catch (e) { /* page may be torn down */ }
    }
  }

  function deriveRealm(cfg) {
    if (cfg.realm) return cfg.realm;
    try {
      const u = new URL(cfg.ws_url);
      return u.hostname;
    } catch {
      return '';
    }
  }

  function buildUri(cfg) {
    const realm = deriveRealm(cfg);
    return `sip:${cfg.extension}@${realm}`;
  }

  function peerLabel(session) {
    try {
      const uri = session.remote_identity?.uri;
      const display = session.remote_identity?.display_name;
      if (display) return display;
      if (uri) return uri.user || String(uri);
    } catch {}
    return 'unknown';
  }

  function ensureAudioElement() {
    if (PHONE.audioEl) return PHONE.audioEl;
    const a = document.createElement('audio');
    a.id = 'sip-remote-audio';
    a.autoplay = true;
    a.style.display = 'none';
    document.body.appendChild(a);
    PHONE.audioEl = a;
    return a;
  }

  function attachRemoteStream(session) {
    const audio = ensureAudioElement();
    const pc = session.connection;
    if (!pc) return;
    // Older browsers fire 'addstream'; newer use 'track'.
    pc.addEventListener('addstream', (e) => { audio.srcObject = e.stream; });
    pc.addEventListener('track', (e) => {
      if (!e.streams || !e.streams[0]) return;
      audio.srcObject = e.streams[0];
    });
  }

  function recordCall(direction, peer, status, durationS) {
    PHONE.history.unshift({
      ts: Date.now() / 1000,
      direction,
      peer,
      status,
      duration_s: Math.max(0, durationS | 0),
    });
    if (PHONE.history.length > 50) PHONE.history.length = 50;
    emit({ type: 'history' });
  }

  function wireSessionEvents(session, direction) {
    attachRemoteStream(session);

    session.on('progress',   () => emit({ type: 'session', state: 'progress',  peer: peerLabel(session), direction }));
    session.on('accepted',   () => {
      PHONE.callStartedAt = Date.now();
      emit({ type: 'session', state: 'connected', peer: peerLabel(session), direction });
    });
    session.on('confirmed',  () => emit({ type: 'session', state: 'connected', peer: peerLabel(session), direction }));
    session.on('ended',      (e) => {
      const peer = peerLabel(session);
      const dur = PHONE.callStartedAt ? (Date.now() - PHONE.callStartedAt) / 1000 : 0;
      recordCall(direction, peer, 'completed', dur);
      PHONE.callStartedAt = null;
      PHONE.activeSession = null;
      emit({ type: 'session', state: 'ended', peer, direction, cause: e?.cause });
    });
    session.on('failed', (e) => {
      const peer = peerLabel(session);
      const dur = PHONE.callStartedAt ? (Date.now() - PHONE.callStartedAt) / 1000 : 0;
      const status = direction === 'in' && !PHONE.callStartedAt ? 'missed' : 'failed';
      recordCall(direction, peer, status, dur);
      PHONE.callStartedAt = null;
      PHONE.activeSession = null;
      PHONE.incomingSession = null;
      emit({ type: 'session', state: 'failed', peer, direction, cause: e?.cause });
    });
  }

  // ---------- public API ----------------------------------------------

  function subscribe(cb) {
    PHONE.listeners.add(cb);
    return () => PHONE.listeners.delete(cb);
  }

  async function startPhone(cfg) {
    if (typeof JsSIP === 'undefined') {
      emit({ type: 'fatal', message: 'JsSIP failed to load (CDN blocked?).' });
      return false;
    }
    if (!cfg || !cfg.ws_url || !cfg.extension) {
      emit({ type: 'fatal', message: 'Missing SIP config (ws_url / extension).' });
      return false;
    }
    stopPhone();
    PHONE.config = cfg;

    const socket = new JsSIP.WebSocketInterface(cfg.ws_url);
    const ua = new JsSIP.UA({
      uri: buildUri(cfg),
      password: cfg.password,
      display_name: cfg.display_name || undefined,
      sockets: [socket],
      register: true,
      session_timers: false,
    });
    PHONE.ua = ua;

    ua.on('connected',          () => emit({ type: 'transport', state: 'connected' }));
    ua.on('disconnected',       () => emit({ type: 'transport', state: 'disconnected' }));
    ua.on('registered',         () => emit({ type: 'registered', extension: cfg.extension }));
    ua.on('unregistered',       () => emit({ type: 'unregistered' }));
    ua.on('registrationFailed', (e) => emit({ type: 'register_failed', cause: e?.cause || 'unknown' }));

    ua.on('newRTCSession', (e) => {
      const session = e.session;
      if (session.direction === 'incoming') {
        PHONE.incomingSession = session;
        wireSessionEvents(session, 'in');
        emit({ type: 'incoming', peer: peerLabel(session) });
      } else {
        PHONE.activeSession = session;
        wireSessionEvents(session, 'out');
      }
    });

    try {
      ua.start();
      emit({ type: 'starting' });
      return true;
    } catch (err) {
      emit({ type: 'fatal', message: `Failed to start UA: ${err.message || err}` });
      return false;
    }
  }

  function stopPhone() {
    try { PHONE.activeSession?.terminate(); } catch {}
    try { PHONE.incomingSession?.terminate(); } catch {}
    try { PHONE.ua?.stop(); } catch {}
    PHONE.activeSession = null;
    PHONE.incomingSession = null;
    PHONE.callStartedAt = null;
    PHONE.ua = null;
    if (PHONE.audioEl) { try { PHONE.audioEl.srcObject = null; } catch {} }
    emit({ type: 'stopped' });
  }

  function dial(target) {
    if (!PHONE.ua) return { ok: false, error: 'Phone not started.' };
    if (PHONE.activeSession) return { ok: false, error: 'Already on a call.' };
    if (!target) return { ok: false, error: 'No number.' };
    const realm = deriveRealm(PHONE.config);
    // Accept bare extensions ('1001') or full URIs ('sip:1001@host').
    const uri = target.startsWith('sip:') ? target : `sip:${target}@${realm}`;
    try {
      const session = PHONE.ua.call(uri, {
        mediaConstraints: { audio: true, video: false },
        pcConfig: { iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] },
      });
      PHONE.activeSession = session;
      // wireSessionEvents is called from 'newRTCSession' fired by the UA.
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e.message || String(e) };
    }
  }

  function answer() {
    if (!PHONE.incomingSession) return;
    try {
      PHONE.incomingSession.answer({
        mediaConstraints: { audio: true, video: false },
        pcConfig: { iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] },
      });
      PHONE.activeSession = PHONE.incomingSession;
      PHONE.incomingSession = null;
    } catch (e) {
      emit({ type: 'fatal', message: `answer failed: ${e.message || e}` });
    }
  }

  function rejectIncoming() {
    try { PHONE.incomingSession?.terminate({ status_code: 486, reason_phrase: 'Busy Here' }); } catch {}
    PHONE.incomingSession = null;
    emit({ type: 'incoming_cleared' });
  }

  function hangup() {
    try { PHONE.activeSession?.terminate(); } catch {}
  }

  function setMuted(mute) {
    const s = PHONE.activeSession;
    if (!s) return;
    try {
      if (mute) s.mute({ audio: true });
      else      s.unmute({ audio: true });
      emit({ type: 'muted', muted: !!mute });
    } catch (e) {
      emit({ type: 'fatal', message: `mute failed: ${e.message || e}` });
    }
  }

  function sendDtmf(tone) {
    try { PHONE.activeSession?.sendDTMF(String(tone)); } catch {}
  }

  function getHistory() { return PHONE.history.slice(); }
  function isRegistered() { return !!PHONE.ua && PHONE.ua.isRegistered(); }
  function isRegistering() { return !!PHONE.ua && !PHONE.ua.isRegistered(); }
  function callState() {
    if (PHONE.activeSession) return 'in-call';
    if (PHONE.incomingSession) return 'ringing';
    if (isRegistered()) return 'idle';
    return 'offline';
  }

  window.SipPhone = {
    startPhone,
    stopPhone,
    subscribe,
    dial,
    answer,
    rejectIncoming,
    hangup,
    setMuted,
    sendDtmf,
    getHistory,
    isRegistered,
    isRegistering,
    callState,
  };
})();
