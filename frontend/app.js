// =============================================================
// PW Demo Master — frontend shell
// =============================================================

const PREFS_KEY = 'pwdemo.prefs';

const prefs = loadPrefs();

const state = {
  frigate: {
    status: 'idle',
    statusText: 'Not configured',
    url: null,
  },
  ha: {
    status: 'idle',
    statusText: 'Not configured',
    url: null,
    tokenSet: false,
  },
  mqtt: {
    status: 'idle',
    statusText: 'Not configured',
  },
  healthTimer: null,
  thumbsTimer: null,   // refreshes Frigate Home thumbnails
  liveTimer: null,     // refreshes modal live view
};

function loadPrefs() {
  try {
    return Object.assign(
      { theme: 'light', sidebarCollapsed: false },
      JSON.parse(localStorage.getItem(PREFS_KEY)) || {},
    );
  } catch {
    return { theme: 'light', sidebarCollapsed: false };
  }
}

function savePrefs() {
  localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
}

// =============================================================
// API client
// =============================================================
const Api = {
  async getJSON(path) {
    const res = await fetch(path, { headers: { Accept: 'application/json' } });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`HTTP ${res.status}${text ? ` — ${text.slice(0, 160)}` : ''}`);
    }
    return res.json();
  },

  async postJSON(path, body) {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`HTTP ${res.status}${text ? ` — ${text.slice(0, 160)}` : ''}`);
    }
    return res.json();
  },
};

const Frigate = {
  getConfig:  ()    => Api.getJSON('/api/frigate/config'),
  setConfig:  (url) => Api.postJSON('/api/frigate/config', { url }),
  getHealth:  ()    => Api.getJSON('/api/frigate/health'),
  getCameras: ()    => Api.getJSON('/api/frigate/cameras'),
  getLabels:  ()    => Api.getJSON('/api/frigate/labels'),
  getEvents:  (filters = {}) => {
    const qs = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v);
    });
    const q = qs.toString();
    return Api.getJSON(`/api/frigate/events${q ? `?${q}` : ''}`);
  },
};

const HA = {
  getConfig:   ()                => Api.getJSON('/api/homeassistant/config'),
  setConfig:   (url, token)      => Api.postJSON('/api/homeassistant/config', { url, token }),
  getHealth:   ()                => Api.getJSON('/api/homeassistant/health'),
  getEntities: (domain)          => Api.getJSON(`/api/homeassistant/entities${domain ? `?domain=${encodeURIComponent(domain)}` : ''}`),
  getEntity:   (id)              => Api.getJSON(`/api/homeassistant/entity/${encodeURIComponent(id)}`),
  getDomains:  ()                => Api.getJSON('/api/homeassistant/domains'),
  getAreas:    ()                => Api.getJSON('/api/homeassistant/areas'),
  getKnowledge:()                => Api.getJSON('/api/homeassistant/knowledge'),
  getDomainKnowledge: (d)        => Api.getJSON(`/api/homeassistant/knowledge/${encodeURIComponent(d)}`),
  call:        (domain, service, data = {}) =>
    Api.postJSON('/api/homeassistant/call', { domain, service, service_data: data }),
};

const LiveAgent = {
  getConfig: () => Api.getJSON('/api/live-agent/config'),
  setConfig: (api_key, model) => Api.postJSON('/api/live-agent/config', { api_key, model }),
};

const Mqtt = {
  getConfig: ()       => Api.getJSON('/api/mqtt/config'),
  setConfig: (patch)  => Api.postJSON('/api/mqtt/config', patch),
  getHealth: ()       => Api.getJSON('/api/mqtt/health'),
};

const Sip = {
  getConfig: ()       => Api.getJSON('/api/sip/config'),
  setConfig: (patch)  => Api.postJSON('/api/sip/config', patch),
  getHealth: ()       => Api.getJSON('/api/sip/health'),
};

const Ollama = {
  getConfig: () => Api.getJSON('/api/ai-camera/ollama/config'),
  setConfig: (url) => Api.postJSON('/api/ai-camera/ollama/config', { url }),
  getHealth: () => Api.getJSON('/api/ai-camera/ollama/health'),
  listModels: () => Api.getJSON('/api/ai-camera/ollama/models'),
};

const AiCameraRules = {
  listModels: () => Api.getJSON('/api/ai-camera/models'),
};

// =============================================================
// Header health indicators
// =============================================================
function setPillStatus(prefix, status, text) {
  const dot = document.getElementById(`${prefix}-dot`);
  const txt = document.getElementById(`${prefix}-status-text`);
  if (!dot || !txt) return;
  dot.classList.remove('ok', 'err', 'warn', 'checking');
  if (status !== 'idle') dot.classList.add(status);
  txt.textContent = text;
}

function setHealth(status, text) {
  state.frigate.status = status;
  state.frigate.statusText = text;
  setPillStatus('frigate', status, text);
}

function setHaHealth(status, text) {
  state.ha.status = status;
  state.ha.statusText = text;
  setPillStatus('ha', status, text);
}

function setMqttHealth(status, text) {
  state.mqtt.status = status;
  state.mqtt.statusText = text;
  setPillStatus('mqtt', status, text);
}

function setSipHealth(status, text) {
  setPillStatus('sip', status, text);
}

async function refreshHealth() {
  const [frigateRes, haRes, mqttRes, sipRes] = await Promise.allSettled([
    Frigate.getHealth(),
    HA.getHealth(),
    Mqtt.getHealth(),
    Sip.getHealth(),
  ]);
  if (frigateRes.status === 'fulfilled') setHealth(frigateRes.value.status, frigateRes.value.message || '');
  else                                    setHealth('err', 'Backend unreachable');
  if (haRes.status === 'fulfilled')      setHaHealth(haRes.value.status, haRes.value.message || '');
  else                                    setHaHealth('err', 'Backend unreachable');
  if (mqttRes.status === 'fulfilled')    setMqttHealth(mqttRes.value.status, mqttRes.value.message || '');
  else                                    setMqttHealth('err', 'Backend unreachable');
  // SIP pill shows config + live JsSIP register state. The Extension page
  // overrides this when registration succeeds/fails — refreshHealth only
  // reflects the *config* level (configured / unconfigured / missing pw).
  if (sipRes.status === 'fulfilled' && !window.SipPhone?.isRegistering?.()) {
    setSipHealth(sipRes.value.status, sipRes.value.message || '');
  } else if (sipRes.status !== 'fulfilled') {
    setSipHealth('err', 'Backend unreachable');
  }
}

function startHealthPolling() {
  if (state.healthTimer) clearInterval(state.healthTimer);
  state.healthTimer = setInterval(refreshHealth, 15000);
}

// =============================================================
// Router
// =============================================================
const routes = {
  'home':                  { title: 'Home',                  render: renderHome },
  'settings':              { title: 'Settings',              render: renderSettings },
  'frigate/home':          { title: 'Frigate · Home',        render: renderFrigateHome },
  'frigate/events':        { title: 'Frigate · Events',      render: renderFrigateEvents },
  'smart-home/main':       { title: 'Smart Home · Main',     render: renderSmartHomeMain },
  'smart-home/test':       { title: 'Smart Home · Test',     render: renderSmartHomeTest },
  'smart-home/live-agent': { title: 'Smart Home · Live Agent', render: renderLiveAgent },
  'ai-camera/main':        { title: 'AI-Camera · Main',       render: renderAiCameraMain },
  'ai-camera/rules':       { title: 'AI-Camera · Rules',      render: renderAiCameraRules },
  'ai-camera/playground':  { title: 'AI-Camera · Playground', render: renderAiCameraPlayground },
  'ai-camera/test-model':  { title: 'AI-Camera · Test AI Model', render: renderAiCameraTestModel },
  'sip/extension':         { title: 'SIP Phone · Extension',     render: renderSipExtension },
};

function currentRoute() {
  const hash = (location.hash || '#/home').replace(/^#\/?/, '');
  return hash || 'home';
}

function navigate() {
  const route = currentRoute();
  const entry = routes[route] || { title: 'PW Demo Master', render: renderNotFound };

  document.querySelectorAll('.nav-item[data-route]').forEach((el) => {
    el.classList.toggle('active', el.dataset.route === route);
  });

  if (route.startsWith('frigate/')) {
    document.querySelector('.nav-group[data-group="frigate"]')?.classList.add('open');
  }

  // Leaving Frigate Home? Stop background refresh + motion WS.
  if (route !== 'frigate/home') {
    stopThumbsRefresh();
    try { closeFrigateHomeMotionWs(); } catch {}
  }

  // Leaving the Live Agent page? Drop the session.
  if (route !== 'smart-home/live-agent' && window.LiveAgentSession) {
    try { window.LiveAgentSession.stop(); } catch {}
  }

  // Open the parent nav group when on a child route.
  if (route.startsWith('smart-home/')) {
    document.querySelector('.nav-group[data-group="smart-home"]')?.classList.add('open');
  }
  if (route.startsWith('ai-camera/')) {
    document.querySelector('.nav-group[data-group="ai-camera"]')?.classList.add('open');
  }
  if (route.startsWith('sip/')) {
    document.querySelector('.nav-group[data-group="sip"]')?.classList.add('open');
  }

  // Leaving the Playground page? Drop the session.
  if (route !== 'ai-camera/playground' && window.AiCameraSession?.isActive?.()) {
    try { window.AiCameraSession.stop(); } catch {}
  }
  // Leaving the SIP Extension page? Tear down the softphone.
  if (route !== 'sip/extension' && window.SipPhone) {
    try { window.SipPhone.stopPhone(); } catch {}
  }

  // Leaving the Rules page? Close its motion WS + unwire the event listener.
  if (route !== 'ai-camera/rules') {
    try { tearDownRulesPage(); } catch {}
  }

  document.getElementById('page-title').textContent = entry.title;
  entry.render(document.getElementById('content'));
}

// =============================================================
// Pages
// =============================================================
function renderHome(root) {
  root.innerHTML = `
    <div class="page-header">
      <h1>Welcome to Primewave Demo Master</h1>
      <p>Showcase site for Home Assistant, Frigate, SIP, and Gemini Live Assistant integrations.</p>
    </div>

    <div class="card">
      <h2>Integrations</h2>
      <p class="hint">Configure connections in <a href="#/settings">Settings</a>. Each integration gets its own area in the sidebar.</p>
      <ul>
        <li><strong>Frigate</strong> — NVR with object detection. <a href="#/frigate/home">Browse cameras</a> after configuring the URL.</li>
        <li><strong>Home Assistant</strong> — coming soon.</li>
        <li><strong>SIP</strong> — coming soon.</li>
        <li><strong>Gemini Live Assistant</strong> — coming soon.</li>
      </ul>
    </div>
  `;
}

function renderSettings(root) {
  root.innerHTML = `
    <div class="page-header">
      <h1>Settings</h1>
      <p>Configure connections to your integrations.</p>
    </div>

    <div class="card">
      <h2>Frigate</h2>
      <p class="hint">Enter the base URL of your Frigate instance (e.g. <code>http://192.168.1.50:5000</code>). The backend connects to Frigate on your behalf — no CORS issues.</p>
      <label class="field">
        <span class="lbl">Frigate URL</span>
        <input id="frigate-url" type="url" placeholder="http://frigate.local:5000" />
      </label>
      <div class="btn-row">
        <button class="btn" id="btn-frigate-connect">Connect</button>
        <button class="btn secondary" id="btn-frigate-clear">Clear</button>
      </div>
      <div class="feedback" id="frigate-feedback"></div>
    </div>

    <div class="card">
      <h2>Home Assistant</h2>
      <p class="hint">Enter your Home Assistant base URL and a <strong>Long-Lived Access Token</strong> (HA → Profile → Security → Long-Lived Access Tokens).</p>
      <label class="field">
        <span class="lbl">Home Assistant URL</span>
        <input id="ha-url" type="url" placeholder="http://homeassistant.local:8123" />
      </label>
      <label class="field">
        <span class="lbl">Access token</span>
        <input id="ha-token" type="password" placeholder="eyJhbGciOiJI…" autocomplete="off" />
        <span class="hint" style="margin-top:6px;display:block">Leave blank when reconnecting to keep the saved token.</span>
      </label>
      <div class="btn-row">
        <button class="btn" id="btn-ha-connect">Connect</button>
        <button class="btn secondary" id="btn-ha-clear">Clear</button>
      </div>
      <div class="feedback" id="ha-feedback"></div>
    </div>

    <div class="card">
      <h2>MQTT broker</h2>
      <p class="hint">Used to receive push notifications from Frigate (motion + detected objects) without polling. Point this at the same broker your Frigate publishes to.</p>
      <div style="display:grid;grid-template-columns:1fr 120px;gap:10px">
        <label class="field">
          <span class="lbl">Host</span>
          <input id="mqtt-host" type="text" placeholder="192.168.1.10 or mosquitto.local" />
        </label>
        <label class="field">
          <span class="lbl">Port</span>
          <input id="mqtt-port" type="number" value="1883" min="1" />
        </label>
      </div>
      <label class="field">
        <span class="lbl">Username (optional)</span>
        <input id="mqtt-user" type="text" autocomplete="off" />
      </label>
      <label class="field">
        <span class="lbl">Password (optional)</span>
        <input id="mqtt-pass" type="password" autocomplete="off" />
        <span class="hint" style="margin-top:6px;display:block">Leave blank to keep the saved password.</span>
      </label>
      <label class="field">
        <span class="lbl">Frigate topic prefix</span>
        <input id="mqtt-prefix" type="text" value="frigate" />
        <span class="hint" style="margin-top:6px;display:block">Default is <code>frigate</code>. Match the <code>topic_prefix</code> in your Frigate <code>mqtt</code> config.</span>
      </label>
      <div class="btn-row">
        <button class="btn" id="btn-mqtt-save">Save &amp; reconnect</button>
        <button class="btn secondary" id="btn-mqtt-clear">Clear</button>
      </div>
      <div class="feedback" id="mqtt-feedback"></div>
    </div>

    <div class="card">
      <h2>Ollama (local vision)</h2>
      <p class="hint">Optional. Point at a local Ollama daemon (e.g. <code>http://localhost:11434</code>) to run AI-Camera Rules against vision models on your own GPU — moondream, llava, llama3.2-vision, etc. Each rule picks its own model.</p>
      <label class="field">
        <span class="lbl">Ollama base URL</span>
        <input id="ollama-url" type="url" placeholder="http://localhost:11434" />
      </label>
      <div class="btn-row">
        <button class="btn" id="btn-ollama-save">Save &amp; test</button>
        <button class="btn secondary" id="btn-ollama-clear">Clear</button>
      </div>
      <div class="feedback" id="ollama-feedback"></div>
      <div id="ollama-models" class="hint" style="margin-top:8px"></div>
    </div>

    <div class="card">
      <h2>Gemini Live Agent</h2>
      <p class="hint">Paste your Google AI Studio API key. Used to drive the Smart Home → Live Agent page (audio in/out, vision, Home Assistant tool calls).</p>
      <label class="field">
        <span class="lbl">Gemini API key</span>
        <input id="gemini-key" type="password" placeholder="AIza…" autocomplete="off" />
        <span class="hint" style="margin-top:6px;display:block">Leave blank when reconnecting to keep the saved key.</span>
      </label>
      <label class="field">
        <span class="lbl">Model</span>
        <input id="gemini-model" type="text" placeholder="gemini-2.0-flash-live-001" />
        <span class="hint" style="margin-top:6px;display:block">Use a Live-capable model id. Default works for most accounts.</span>
      </label>
      <div class="btn-row">
        <button class="btn" id="btn-gemini-save">Save</button>
        <button class="btn secondary" id="btn-gemini-clear">Clear</button>
      </div>
      <div class="feedback" id="gemini-feedback"></div>
    </div>

    <div class="card">
      <h2>SIP softphone</h2>
      <p class="hint">Credentials for the browser-based softphone (SIP Phone → Extension). Audio/signalling go browser → PBX directly via SIP-over-WebSocket + WebRTC; nothing flows through this backend. Suggested PBX: <strong>Asterisk</strong> or <strong>FreePBX</strong> in Proxmox with <code>chan_pjsip</code> configured with <code>transport=wss</code>.</p>
      <label class="field">
        <span class="lbl">WebSocket URL</span>
        <input id="sip-ws-url" type="text" placeholder="wss://pbx.example.com:8089/ws" />
        <span class="hint" style="margin-top:6px;display:block">For Asterisk default: <code>wss://&lt;pbx&gt;:8089/ws</code>. Browsers require <code>wss://</code> (TLS) when the page itself is served over HTTPS.</span>
      </label>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
        <label class="field">
          <span class="lbl">Extension</span>
          <input id="sip-extension" type="text" placeholder="1001" autocomplete="off" />
        </label>
        <label class="field">
          <span class="lbl">SIP realm (optional)</span>
          <input id="sip-realm" type="text" placeholder="defaults to the WS host" />
        </label>
      </div>
      <label class="field">
        <span class="lbl">Password</span>
        <input id="sip-password" type="password" autocomplete="off" />
        <span class="hint" style="margin-top:6px;display:block">Leave blank to keep the saved password.</span>
      </label>
      <label class="field">
        <span class="lbl">Display name (optional)</span>
        <input id="sip-display-name" type="text" placeholder="Reception phone" />
      </label>
      <div class="btn-row">
        <button class="btn" id="btn-sip-save">Save</button>
        <button class="btn secondary" id="btn-sip-clear">Clear</button>
      </div>
      <div class="feedback" id="sip-feedback"></div>
    </div>
  `;

  initFrigateSettings();
  initHASettings();
  initMqttSettings();
  initOllamaSettings();
  initGeminiSettings();
  initSipSettings();
}

function initSipSettings() {
  const wsEl    = document.getElementById('sip-ws-url');
  const extEl   = document.getElementById('sip-extension');
  const realmEl = document.getElementById('sip-realm');
  const passEl  = document.getElementById('sip-password');
  const dnEl    = document.getElementById('sip-display-name');
  const fb      = document.getElementById('sip-feedback');

  Sip.getConfig().then((c) => {
    if (c.ws_url)       wsEl.value    = c.ws_url;
    if (c.extension)    extEl.value   = c.extension;
    if (c.realm)        realmEl.value = c.realm;
    if (c.display_name) dnEl.value    = c.display_name;
    if (c.password_set) passEl.placeholder = '••••••• (saved — leave blank to keep)';
  }).catch(() => {});

  document.getElementById('btn-sip-save').addEventListener('click', async () => {
    const patch = {
      ws_url:       wsEl.value.trim(),
      extension:    extEl.value.trim(),
      realm:        realmEl.value.trim(),
      display_name: dnEl.value.trim(),
    };
    if (passEl.value) patch.password = passEl.value;
    if (!patch.ws_url || !patch.extension) {
      showFeedback(fb, 'err', 'WebSocket URL and Extension are required.');
      return;
    }
    try {
      const saved = await Sip.setConfig(patch);
      passEl.value = '';
      if (saved.password_set) passEl.placeholder = '••••••• (saved — leave blank to keep)';
      showFeedback(fb, 'ok', 'Saved. The Extension page will use this on next register.');
    } catch (e) {
      showFeedback(fb, 'err', `Failed: ${e.message}`);
    }
  });

  document.getElementById('btn-sip-clear').addEventListener('click', async () => {
    try {
      await Sip.setConfig({ ws_url: '', extension: '', realm: '', display_name: '', password: '' });
      wsEl.value = ''; extEl.value = ''; realmEl.value = ''; passEl.value = ''; dnEl.value = '';
      passEl.placeholder = '';
      showFeedback(fb, 'ok', 'Cleared.');
    } catch (e) {
      showFeedback(fb, 'err', `Failed: ${e.message}`);
    }
  });
}

function initOllamaSettings() {
  const urlEl = document.getElementById('ollama-url');
  const feedback = document.getElementById('ollama-feedback');
  const modelsEl = document.getElementById('ollama-models');

  const renderHealthAndModels = async (cfgHealth) => {
    if (!cfgHealth) {
      try { cfgHealth = await Ollama.getHealth(); } catch { cfgHealth = { status: 'err', message: 'unreachable' }; }
    }
    if (cfgHealth.status === 'ok') {
      const ver = cfgHealth.version ? ` (v${cfgHealth.version})` : '';
      showFeedback(feedback, 'ok', `Connected${ver}.`);
      try {
        const { models } = await Ollama.listModels();
        if (!models.length) {
          modelsEl.textContent = 'No models installed. Pull one first (e.g. `ollama pull moondream`).';
        } else {
          modelsEl.innerHTML = `Installed models: ${models.map((m) => `<code>${escapeHtml(m.name)}</code>`).join(', ')}`;
        }
      } catch (e) {
        modelsEl.textContent = `Couldn't list models: ${e.message}`;
      }
    } else {
      modelsEl.textContent = '';
      showFeedback(feedback, 'err', cfgHealth.message || 'Unreachable.');
    }
  };

  Ollama.getConfig().then((c) => {
    if (c.url) {
      urlEl.value = c.url;
      renderHealthAndModels();
    }
  }).catch(() => {});

  document.getElementById('btn-ollama-save').addEventListener('click', async () => {
    const raw = urlEl.value.trim();
    showFeedback(feedback, 'ok', 'Saving…');
    modelsEl.textContent = '';
    try {
      const out = await Ollama.setConfig(raw);
      if (out.url) urlEl.value = out.url;
      await renderHealthAndModels(out.health);
    } catch (e) {
      showFeedback(feedback, 'err', `Failed: ${e.message}`);
    }
  });

  document.getElementById('btn-ollama-clear').addEventListener('click', async () => {
    try {
      await Ollama.setConfig('');
      urlEl.value = '';
      modelsEl.textContent = '';
      showFeedback(feedback, 'ok', 'Cleared.');
    } catch (e) {
      showFeedback(feedback, 'err', `Failed: ${e.message}`);
    }
  });
}

function initMqttSettings() {
  const hostEl   = document.getElementById('mqtt-host');
  const portEl   = document.getElementById('mqtt-port');
  const userEl   = document.getElementById('mqtt-user');
  const passEl   = document.getElementById('mqtt-pass');
  const prefixEl = document.getElementById('mqtt-prefix');
  const feedback = document.getElementById('mqtt-feedback');

  Mqtt.getConfig().then((c) => {
    if (c.host)        hostEl.value   = c.host;
    if (c.port)        portEl.value   = c.port;
    if (c.username)    userEl.value   = c.username;
    if (c.topic_prefix) prefixEl.value = c.topic_prefix;
    if (c.password_set) passEl.placeholder = '••••••• (saved — leave blank to keep)';
  }).catch(() => {});

  document.getElementById('btn-mqtt-save').addEventListener('click', async () => {
    const patch = {
      host:         hostEl.value.trim(),
      port:         parseInt(portEl.value, 10) || 1883,
      username:     userEl.value,
      topic_prefix: prefixEl.value.trim() || 'frigate',
    };
    if (passEl.value) patch.password = passEl.value;
    if (!patch.host) { showFeedback(feedback, 'err', 'MQTT host is required.'); return; }

    showFeedback(feedback, 'ok', 'Saving and reconnecting…');
    try {
      const saved = await Mqtt.setConfig(patch);
      passEl.value = '';
      if (saved.password_set) passEl.placeholder = '••••••• (saved — leave blank to keep)';
      // Give the service a moment to (re)connect, then probe health.
      await new Promise((r) => setTimeout(r, 700));
      const h = await Mqtt.getHealth();
      if (h.status === 'ok') showFeedback(feedback, 'ok', `Connected. ${h.message}`);
      else                   showFeedback(feedback, 'err', `Saved, but: ${h.message}`);
    } catch (e) {
      showFeedback(feedback, 'err', `Failed: ${e.message}`);
    }
  });

  document.getElementById('btn-mqtt-clear').addEventListener('click', async () => {
    try {
      await Mqtt.setConfig({ host: '', username: '', password: '', topic_prefix: 'frigate', port: 1883 });
      hostEl.value = '';
      userEl.value = '';
      passEl.value = '';
      passEl.placeholder = '';
      prefixEl.value = 'frigate';
      portEl.value = 1883;
      showFeedback(feedback, 'ok', 'Cleared.');
    } catch (e) {
      showFeedback(feedback, 'err', `Failed: ${e.message}`);
    }
  });
}

function initGeminiSettings() {
  const keyInput = document.getElementById('gemini-key');
  const modelInput = document.getElementById('gemini-model');
  const feedback = document.getElementById('gemini-feedback');

  LiveAgent.getConfig().then((c) => {
    if (c.model) modelInput.value = c.model;
    if (c.api_key_set) keyInput.placeholder = '••••••• (saved — leave blank to keep)';
  }).catch(() => {});

  document.getElementById('btn-gemini-save').addEventListener('click', async () => {
    const key = keyInput.value;
    const model = modelInput.value.trim();
    try {
      const saved = await LiveAgent.setConfig(key || null, model || null);
      if (saved.model) modelInput.value = saved.model;
      keyInput.value = '';
      if (saved.api_key_set) {
        keyInput.placeholder = '••••••• (saved — leave blank to keep)';
        showFeedback(feedback, 'ok', 'Saved.');
      } else {
        showFeedback(feedback, 'err', 'Saved, but no API key on file. Paste one and save again.');
      }
    } catch (e) {
      showFeedback(feedback, 'err', `Failed: ${e.message}`);
    }
  });

  document.getElementById('btn-gemini-clear').addEventListener('click', async () => {
    try {
      await LiveAgent.setConfig('', null);
      keyInput.value = '';
      keyInput.placeholder = 'AIza…';
      showFeedback(feedback, 'ok', 'API key cleared.');
    } catch (e) {
      showFeedback(feedback, 'err', `Failed: ${e.message}`);
    }
  });
}

function initFrigateSettings() {
  const input = document.getElementById('frigate-url');
  const feedback = document.getElementById('frigate-feedback');

  Frigate.getConfig().then((c) => { if (c.url) input.value = c.url; }).catch(() => {});

  document.getElementById('btn-frigate-connect').addEventListener('click', async () => {
    const raw = input.value.trim();
    if (!raw) { showFeedback(feedback, 'err', 'Please enter a Frigate URL.'); return; }
    showFeedback(feedback, 'ok', 'Connecting…');
    setHealth('checking', 'Checking…');
    try {
      const saved = await Frigate.setConfig(raw);
      if (saved.url) input.value = saved.url;
      const h = await Frigate.getHealth();
      setHealth(h.status, h.message);
      if (h.status === 'ok') {
        const cams = await Frigate.getCameras();
        showFeedback(feedback, 'ok', `Connected. ${cams.length} camera${cams.length === 1 ? '' : 's'} found.`);
      } else {
        showFeedback(feedback, 'err', `Saved URL but Frigate is ${h.message || 'unreachable'}.`);
      }
    } catch (e) {
      setHealth('err', 'Unreachable');
      showFeedback(feedback, 'err', `Failed: ${e.message}`);
    }
  });

  document.getElementById('btn-frigate-clear').addEventListener('click', async () => {
    try {
      await Frigate.setConfig('');
      input.value = '';
      setHealth('idle', 'Not configured');
      showFeedback(feedback, 'ok', 'Cleared.');
    } catch (e) {
      showFeedback(feedback, 'err', `Failed: ${e.message}`);
    }
  });
}

function initHASettings() {
  const urlInput   = document.getElementById('ha-url');
  const tokenInput = document.getElementById('ha-token');
  const feedback   = document.getElementById('ha-feedback');

  HA.getConfig().then((c) => {
    if (c.url) urlInput.value = c.url;
    if (c.token_set) {
      tokenInput.placeholder = '••••••• (saved — leave blank to keep)';
    }
  }).catch(() => {});

  document.getElementById('btn-ha-connect').addEventListener('click', async () => {
    const url = urlInput.value.trim();
    const token = tokenInput.value;
    if (!url) { showFeedback(feedback, 'err', 'Please enter the Home Assistant URL.'); return; }
    showFeedback(feedback, 'ok', 'Connecting…');
    setHaHealth('checking', 'Checking…');
    try {
      // Only send token if user typed something — otherwise keep the saved one.
      const payload = { url };
      if (token) payload.token = token;
      const saved = await HA.setConfig(payload.url, payload.token);
      if (saved.url) urlInput.value = saved.url;
      if (!saved.token_set) {
        showFeedback(feedback, 'err', 'No token saved. Paste a Long-Lived Access Token and click Connect.');
        setHaHealth('err', 'No token');
        return;
      }
      tokenInput.value = '';
      tokenInput.placeholder = '••••••• (saved — leave blank to keep)';
      const h = await HA.getHealth();
      setHaHealth(h.status, h.message);
      if (h.status === 'ok') {
        showFeedback(feedback, 'ok', `Connected. ${h.message}`);
      } else {
        showFeedback(feedback, 'err', `Saved but ${h.message}.`);
      }
    } catch (e) {
      setHaHealth('err', 'Unreachable');
      showFeedback(feedback, 'err', `Failed: ${e.message}`);
    }
  });

  document.getElementById('btn-ha-clear').addEventListener('click', async () => {
    try {
      await HA.setConfig('', '');
      urlInput.value = '';
      tokenInput.value = '';
      tokenInput.placeholder = 'eyJhbGciOiJI…';
      setHaHealth('idle', 'Not configured');
      showFeedback(feedback, 'ok', 'Cleared.');
    } catch (e) {
      showFeedback(feedback, 'err', `Failed: ${e.message}`);
    }
  });
}

async function renderFrigateHome(root) {
  stopThumbsRefresh();
  state.frigate.url = null;

  let cfg;
  try {
    cfg = await Frigate.getConfig();
  } catch (e) {
    root.innerHTML = `<div class="empty-state"><h3>Backend error</h3><p>${escapeHtml(e.message)}</p></div>`;
    return;
  }

  if (!cfg.url) {
    root.innerHTML = `
      <div class="page-header">
        <h1>Frigate · Home</h1>
        <p>Cameras from your Frigate instance.</p>
      </div>
      <div class="empty-state">
        <h3>Frigate not configured</h3>
        <p>Add your Frigate URL in <a href="#/settings">Settings</a> to see cameras here.</p>
      </div>
    `;
    return;
  }

  state.frigate.url = cfg.url;

  root.innerHTML = `
    <div class="page-header">
      <h1>Frigate · Home</h1>
      <p>Recent snapshots from <code>${escapeHtml(cfg.url)}</code>. Click a camera to open a live view.</p>
    </div>
    <div class="card">
      <h2>Cameras</h2>
      <div id="cameras-content"><p class="hint">Loading…</p></div>
    </div>
  `;

  const container = document.getElementById('cameras-content');
  try {
    const cameras = await Frigate.getCameras();
    if (cameras.length === 0) {
      container.innerHTML = `<p class="hint">No cameras configured in Frigate.</p>`;
      return;
    }
    container.innerHTML = `
      <div class="camera-grid">
        ${cameras.map((cam) => `
          <div class="camera-card" data-camera="${escapeHtml(cam.name)}" tabindex="0" role="button" aria-label="Open live view for ${escapeHtml(cam.name)}">
            <div class="camera-thumb">
              <img class="cam-thumb-img" data-src="${escapeHtml(cam.snapshot_path)}" alt="${escapeHtml(cam.name)}"
                onerror="this.replaceWith(Object.assign(document.createElement('div'),{textContent:'No snapshot',style:'color:#98a2b3;font-size:12px;padding:20px;'}))" />
              <div class="thumb-overlay">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                View live
              </div>
              <div class="cam-badges" data-cam="${escapeHtml(cam.name)}">
                <span class="cam-badge motion" hidden>MOTION</span>
                <span class="cam-badge objects" hidden></span>
              </div>
            </div>
            <div class="camera-body">
              <div class="camera-name">${escapeHtml(cam.name)}</div>
              <div class="camera-meta">${cam.enabled ? 'Enabled' : 'Disabled'}</div>
              <div class="audio-meter" data-cam="${escapeHtml(cam.name)}" title="Audio level (dBFS)">
                <div class="audio-meter-bar"></div>
                <span class="audio-meter-val">—</span>
              </div>
            </div>
          </div>
        `).join('')}
      </div>
    `;

    container.querySelectorAll('.camera-card').forEach((card) => {
      const name = card.dataset.camera;
      card.addEventListener('click', () => openLiveModal(name));
      card.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          openLiveModal(name);
        }
      });
    });

    refreshThumbs(); // immediate set
    startThumbsRefresh();
    ensureFrigateHomeMotionWs();
  } catch (e) {
    container.innerHTML = `<p class="hint" style="color:var(--err)">Failed to load cameras: ${escapeHtml(e.message)}</p>`;
  }
}

// -------------------------------------------------------------
// Frigate Home — motion / objects / audio per camera card
// -------------------------------------------------------------
const FRIGATE_HOME = {
  motion: {},          // cam -> { motion, objects, audio_dbfs, audio_labels }
  ws: null,
  reconnect: null,
};

function ensureFrigateHomeMotionWs() {
  if (FRIGATE_HOME.ws && FRIGATE_HOME.ws.readyState <= WebSocket.OPEN) return;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  let ws;
  try { ws = new WebSocket(`${proto}//${location.host}/api/frigate/motion/ws`); }
  catch { scheduleFrigateHomeReconnect(); return; }
  FRIGATE_HOME.ws = ws;
  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.type === 'snapshot') {
      FRIGATE_HOME.motion = msg.cameras || {};
      Object.keys(FRIGATE_HOME.motion).forEach(updateCameraCardBadges);
    } else if (msg.type === 'motion') {
      FRIGATE_HOME.motion[msg.camera] = {
        motion: !!msg.motion,
        objects: msg.objects || [],
        audio_dbfs: msg.audio_dbfs ?? null,
        audio_labels: msg.audio_labels || [],
      };
      updateCameraCardBadges(msg.camera);
    }
  };
  ws.onclose = () => { FRIGATE_HOME.ws = null; scheduleFrigateHomeReconnect(); };
  ws.onerror = () => { try { ws.close(); } catch {} };
}

function scheduleFrigateHomeReconnect() {
  // Only reconnect if Frigate Home is still mounted.
  if (!document.querySelector('.camera-grid')) return;
  clearTimeout(FRIGATE_HOME.reconnect);
  FRIGATE_HOME.reconnect = setTimeout(ensureFrigateHomeMotionWs, 3000);
}

function closeFrigateHomeMotionWs() {
  clearTimeout(FRIGATE_HOME.reconnect);
  FRIGATE_HOME.reconnect = null;
  if (FRIGATE_HOME.ws) { try { FRIGATE_HOME.ws.close(); } catch {} FRIGATE_HOME.ws = null; }
  FRIGATE_HOME.motion = {};
}

function updateCameraCardBadges(camera) {
  const info = FRIGATE_HOME.motion[camera] || { motion: false, objects: [], audio_dbfs: null, audio_labels: [] };
  const badges = document.querySelector(`.cam-badges[data-cam="${CSS.escape(camera)}"]`);
  if (badges) {
    const motionEl = badges.querySelector('.cam-badge.motion');
    if (motionEl) motionEl.hidden = !info.motion;
    const objectsEl = badges.querySelector('.cam-badge.objects');
    if (objectsEl) {
      const labels = info.objects || [];
      if (labels.length) {
        objectsEl.textContent = labels.join(', ').toUpperCase();
        objectsEl.hidden = false;
      } else {
        objectsEl.hidden = true;
      }
    }
  }
  const meter = document.querySelector(`.audio-meter[data-cam="${CSS.escape(camera)}"]`);
  if (meter) applyAudioMeter(meter, info);
}

function applyAudioMeter(meter, info) {
  const bar = meter.querySelector('.audio-meter-bar');
  const val = meter.querySelector('.audio-meter-val');
  const dbfs = info.audio_dbfs;
  if (dbfs == null || !Number.isFinite(dbfs)) {
    if (bar) bar.style.width = '0%';
    if (val) val.textContent = info.audio_labels?.length ? info.audio_labels.join(', ') : '—';
    meter.classList.remove('hot', 'warm');
    return;
  }
  // -60 dBFS → 0%, 0 dBFS → 100%
  const pct = Math.max(0, Math.min(100, ((dbfs + 60) / 60) * 100));
  if (bar) bar.style.width = pct.toFixed(0) + '%';
  if (val) {
    const labels = info.audio_labels?.length ? ` · ${info.audio_labels.join(', ')}` : '';
    val.textContent = `${dbfs.toFixed(0)} dBFS${labels}`;
  }
  meter.classList.toggle('hot', pct >= 80);
  meter.classList.toggle('warm', pct >= 55 && pct < 80);
}

function refreshThumbs() {
  const cb = Date.now();
  document.querySelectorAll('.cam-thumb-img').forEach((img) => {
    const base = img.dataset.src;
    if (base) img.src = `${base}?cb=${cb}`;
  });
}

function startThumbsRefresh() {
  stopThumbsRefresh();
  // 10s is "recent" without hammering Frigate.
  state.thumbsTimer = setInterval(refreshThumbs, 10000);
}

function stopThumbsRefresh() {
  if (state.thumbsTimer) {
    clearInterval(state.thumbsTimer);
    state.thumbsTimer = null;
  }
}

// =============================================================
// Generic modal
// =============================================================
let _modalOnClose = null;

function showModal({ title, sub, openUrl, bodyHtml, onClose }) {
  const backdrop = document.getElementById('modal-backdrop');
  const titleEl  = document.getElementById('modal-title');
  const subEl    = document.getElementById('modal-sub');
  const bodyEl   = document.getElementById('modal-body');
  const openBtn  = document.getElementById('modal-open-frigate');
  if (!backdrop) return;

  titleEl.textContent = title || '';
  subEl.textContent = sub || '';
  bodyEl.innerHTML = bodyHtml || '';

  if (openUrl) {
    openBtn.href = openUrl;
    openBtn.hidden = false;
  } else {
    openBtn.removeAttribute('href');
    openBtn.hidden = true;
  }

  _modalOnClose = onClose || null;
  backdrop.hidden = false;
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  const backdrop = document.getElementById('modal-backdrop');
  if (!backdrop || backdrop.hidden) return;
  if (_modalOnClose) {
    try { _modalOnClose(); } catch {}
    _modalOnClose = null;
  }
  // Stop any in-flight media (video keeps loading after innerHTML wipe otherwise).
  const bodyEl = document.getElementById('modal-body');
  bodyEl?.querySelectorAll('video').forEach((v) => { try { v.pause(); } catch {} });
  if (bodyEl) bodyEl.innerHTML = '';
  backdrop.hidden = true;
  document.body.style.overflow = '';
}

// ----- Live camera popup --------------------------------------------------
function openLiveModal(cameraName) {
  showModal({
    title: cameraName,
    sub: state.frigate.url || '',
    openUrl: state.frigate.url
      ? `${state.frigate.url}/cameras/${encodeURIComponent(cameraName)}`
      : null,
    bodyHtml: `
      <div class="live-frame">
        <img id="modal-stream" alt="${escapeHtml(cameraName)}" />
        <div class="live-badge"><span class="live-dot"></span>LIVE</div>
      </div>
    `,
    onClose: stopLiveRefresh,
  });

  const imgEl = document.getElementById('modal-stream');
  const tick = () => {
    if (!imgEl) return;
    imgEl.src = `/api/frigate/snapshot/${encodeURIComponent(cameraName)}?h=720&cb=${Date.now()}`;
  };
  tick();
  stopLiveRefresh();
  // ~2 fps quasi-live. Snapshots are quick; this is a demo not production live streaming.
  state.liveTimer = setInterval(tick, 500);
}

function stopLiveRefresh() {
  if (state.liveTimer) {
    clearInterval(state.liveTimer);
    state.liveTimer = null;
  }
}

// ----- Event playback popup -----------------------------------------------
function openEventModal(ev) {
  const camLabel = `${ev.label || 'event'} on ${ev.camera || 'camera'}`;
  const startStr = formatTimestamp(ev.start_time);

  let body;
  if (ev.clip_path) {
    // muted + autoplay so browsers don't block playback; preload="auto" so a
    // frame is decoded immediately (otherwise the video sits black until play).
    body = `
      <div class="live-frame">
        <video controls autoplay muted playsinline preload="auto" src="${escapeHtml(ev.clip_path)}"></video>
      </div>
    `;
  } else if (ev.snapshot_path) {
    body = `
      <div class="live-frame">
        <img src="${escapeHtml(ev.snapshot_path)}" alt="${escapeHtml(camLabel)}" />
      </div>
    `;
  } else {
    body = `
      <div class="live-frame">
        <img src="${escapeHtml(ev.thumbnail_path)}" alt="${escapeHtml(camLabel)}" />
      </div>
    `;
  }

  showModal({
    title: capitalize(camLabel),
    sub: `${startStr}${ev.top_score ? ` · score ${(ev.top_score * 100).toFixed(0)}%` : ''}`,
    openUrl: state.frigate.url
      ? `${state.frigate.url}/cameras/${encodeURIComponent(ev.camera)}`
      : null,
    bodyHtml: body,
  });
}

// =============================================================
// Frigate Events page
// =============================================================
async function renderFrigateEvents(root) {
  let cfg;
  try {
    cfg = await Frigate.getConfig();
  } catch (e) {
    root.innerHTML = `<div class="empty-state"><h3>Backend error</h3><p>${escapeHtml(e.message)}</p></div>`;
    return;
  }

  if (!cfg.url) {
    root.innerHTML = `
      <div class="page-header">
        <h1>Frigate · Events</h1>
        <p>Detection events from your Frigate instance.</p>
      </div>
      <div class="empty-state">
        <h3>Frigate not configured</h3>
        <p>Add your Frigate URL in <a href="#/settings">Settings</a> to see events here.</p>
      </div>
    `;
    return;
  }
  state.frigate.url = cfg.url;

  const now = new Date();
  const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);

  root.innerHTML = `
    <div class="page-header">
      <h1>Frigate · Events</h1>
      <p>Detection events from <code>${escapeHtml(cfg.url)}</code>.</p>
    </div>

    <div class="card">
      <h2>Filters</h2>
      <div class="filter-bar">
        <label class="field">
          <span class="lbl">From</span>
          <input type="datetime-local" id="filter-after" value="${dtLocalString(yesterday)}" />
        </label>
        <label class="field">
          <span class="lbl">To</span>
          <input type="datetime-local" id="filter-before" value="${dtLocalString(now)}" />
        </label>
        <label class="field">
          <span class="lbl">Camera</span>
          <select id="filter-camera"><option value="">All cameras</option></select>
        </label>
        <label class="field">
          <span class="lbl">Type</span>
          <select id="filter-label"><option value="">All types</option></select>
        </label>
        <div class="filter-actions">
          <button class="btn secondary" id="btn-reset">Reset</button>
          <button class="btn" id="btn-apply">Apply</button>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="events-meta">
        <h2 style="margin:0">Events</h2>
        <div class="count" id="events-count"></div>
      </div>
      <div id="events-content"><p class="hint">Loading…</p></div>
    </div>
  `;

  // Populate dropdowns in parallel.
  const camSel   = document.getElementById('filter-camera');
  const labelSel = document.getElementById('filter-label');
  Promise.all([
    Frigate.getCameras().catch(() => []),
    Frigate.getLabels().catch(() => []),
  ]).then(([cams, labels]) => {
    cams.forEach((c) => {
      const opt = document.createElement('option');
      opt.value = c.name; opt.textContent = c.name;
      camSel.appendChild(opt);
    });
    labels.forEach((l) => {
      const opt = document.createElement('option');
      opt.value = l; opt.textContent = capitalize(l);
      labelSel.appendChild(opt);
    });
  });

  const apply = () => loadEvents();
  document.getElementById('btn-apply').addEventListener('click', apply);
  document.getElementById('btn-reset').addEventListener('click', () => {
    document.getElementById('filter-after').value  = dtLocalString(yesterday);
    document.getElementById('filter-before').value = dtLocalString(now);
    camSel.value = '';
    labelSel.value = '';
    apply();
  });

  loadEvents();
}

async function loadEvents() {
  const container = document.getElementById('events-content');
  const countEl   = document.getElementById('events-count');
  if (!container) return;
  container.innerHTML = `<p class="hint">Loading…</p>`;
  countEl.textContent = '';

  const filters = {
    after:  dtLocalToUnix(document.getElementById('filter-after')?.value),
    before: dtLocalToUnix(document.getElementById('filter-before')?.value),
    camera: document.getElementById('filter-camera')?.value || '',
    label:  document.getElementById('filter-label')?.value || '',
    limit:  100,
  };

  try {
    const events = await Frigate.getEvents(filters);
    countEl.textContent = `${events.length} event${events.length === 1 ? '' : 's'}`;

    if (events.length === 0) {
      container.innerHTML = `<p class="hint">No events match these filters.</p>`;
      return;
    }

    container.innerHTML = `
      <div class="events-grid">
        ${events.map((ev) => `
          <div class="event-card" data-id="${escapeHtml(ev.id)}" tabindex="0" role="button"
               aria-label="View event ${escapeHtml(ev.label || '')} on ${escapeHtml(ev.camera || '')}">
            <div class="event-thumb">
              <img src="${escapeHtml(ev.thumbnail_path)}" alt=""
                onerror="this.replaceWith(Object.assign(document.createElement('div'),{textContent:'No thumbnail',style:'color:#98a2b3;font-size:12px;display:flex;align-items:center;justify-content:center;height:100%;'}))" />
              ${ev.has_clip ? `<div class="clip-badge">CLIP</div>` : ''}
            </div>
            <div class="event-body">
              <div class="event-row">
                <span class="event-label-pill">${escapeHtml(ev.label || 'event')}</span>
                ${ev.top_score ? `<span class="event-score">${(ev.top_score * 100).toFixed(0)}%</span>` : ''}
              </div>
              <div class="event-camera">${escapeHtml(ev.camera || '')}</div>
              <div class="event-time">${formatTimestamp(ev.start_time)} · ${formatDuration(ev.start_time, ev.end_time)}</div>
            </div>
          </div>
        `).join('')}
      </div>
    `;

    // Stash events by id so click handlers can look them up without re-encoding.
    const byId = new Map(events.map((e) => [e.id, e]));
    container.querySelectorAll('.event-card').forEach((card) => {
      const id = card.dataset.id;
      const open = () => {
        const ev = byId.get(id);
        if (ev) openEventModal(ev);
      };
      card.addEventListener('click', open);
      card.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
      });
    });
  } catch (e) {
    container.innerHTML = `<p class="hint" style="color:var(--err)">Failed to load events: ${escapeHtml(e.message)}</p>`;
  }
}

// =============================================================
// Smart Home pages
// =============================================================
// =============================================================
// Smart Home Main — area dashboard
// =============================================================
const MAIN = {
  areas: [],
  entityById: new Map(),
  currentAreaId: null,
};

async function renderSmartHomeMain(root) {
  let cfg;
  try { cfg = await HA.getConfig(); }
  catch (e) {
    root.innerHTML = `<div class="empty-state"><h3>Backend error</h3><p>${escapeHtml(e.message)}</p></div>`;
    return;
  }
  if (!cfg.url || !cfg.token_set) {
    root.innerHTML = `
      <div class="page-header">
        <h1>Smart Home</h1>
        <p>Browse your Home Assistant areas and control the entities in each room.</p>
      </div>
      <div class="empty-state">
        <h3>Home Assistant not configured</h3>
        <p>Add your HA URL and token in <a href="#/settings">Settings</a> to load areas.</p>
      </div>
    `;
    return;
  }

  root.innerHTML = `
    <div class="page-header">
      <h1>Smart Home</h1>
      <p>Pick an area to see and control the entities in that room. Controls are tailored to each entity's capabilities.</p>
    </div>
    <div id="sh-content"><p class="hint">Loading…</p></div>
  `;

  await loadMainData();
}

async function loadMainData() {
  const content = document.getElementById('sh-content');
  if (!content) return;
  content.innerHTML = `<p class="hint">Loading…</p>`;
  try {
    const [areas, entities] = await Promise.all([
      HA.getAreas(),
      HA.getEntities(),
    ]);
    MAIN.entityById = new Map(entities.map((e) => [e.entity_id, e]));
    MAIN.areas = areas.map((area) => {
      const ents = (area.entities || [])
        .map((eid) => MAIN.entityById.get(eid))
        .filter(Boolean);
      const domains = [...new Set(ents.map((e) => e.domain))].sort();
      return { id: area.id, name: area.name, entities: ents, domains };
    }).sort((a, b) => a.name.localeCompare(b.name));

    if (MAIN.currentAreaId && MAIN.areas.some((a) => a.id === MAIN.currentAreaId)) {
      renderAreaView();
    } else {
      MAIN.currentAreaId = null;
      renderAreasGrid();
    }
  } catch (e) {
    content.innerHTML = `<p class="hint" style="color:var(--err)">Failed to load: ${escapeHtml(e.message)}</p>`;
  }
}

function renderAreasGrid() {
  const content = document.getElementById('sh-content');
  if (!content) return;
  content.innerHTML = `
    <div class="card">
      <div class="events-meta">
        <h2 style="margin:0">Areas</h2>
        <span class="count">${MAIN.areas.length} areas · ${MAIN.entityById.size} entities</span>
      </div>
      <div class="area-grid">
        ${MAIN.areas.map((a) => `
          <div class="area-card" data-area="${escapeHtml(a.id)}">
            <div class="area-card-name">${escapeHtml(a.name)}</div>
            <div class="area-card-meta">${a.entities.length} entities</div>
            <div class="area-card-domains">
              ${a.domains.slice(0, 6).map((d) => `<span class="domain-chip">${escapeHtml(d)}</span>`).join('')}
              ${a.domains.length > 6 ? `<span class="domain-chip">+${a.domains.length - 6}</span>` : ''}
            </div>
          </div>
        `).join('')}
      </div>
    </div>
  `;
  content.querySelectorAll('.area-card').forEach((card) => {
    card.addEventListener('click', () => {
      MAIN.currentAreaId = card.dataset.area;
      renderAreaView();
    });
  });
}

function renderAreaView() {
  const content = document.getElementById('sh-content');
  if (!content) return;
  const area = MAIN.areas.find((a) => a.id === MAIN.currentAreaId);
  if (!area) { renderAreasGrid(); return; }

  // Group entities by domain so they read like a familiar HA dashboard.
  const groups = new Map();
  for (const ent of area.entities) {
    if (!groups.has(ent.domain)) groups.set(ent.domain, []);
    groups.get(ent.domain).push(ent);
  }
  const groupOrder = ['light', 'switch', 'input_boolean', 'fan', 'climate', 'cover', 'lock',
                      'media_player', 'vacuum', 'scene', 'script', 'automation',
                      'sensor', 'binary_sensor'];
  const sortedDomains = [...groups.keys()].sort((a, b) => {
    const ai = groupOrder.indexOf(a); const bi = groupOrder.indexOf(b);
    if (ai === -1 && bi === -1) return a.localeCompare(b);
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });

  content.innerHTML = `
    <div class="area-header">
      <button class="btn secondary" id="back-to-areas">← All areas</button>
      <div>
        <h2 style="margin:0">${escapeHtml(area.name)}</h2>
        <div class="hint">${area.entities.length} entities · ${area.domains.length} domains</div>
      </div>
      <button class="btn secondary" id="refresh-area" title="Refresh">↻</button>
    </div>

    ${sortedDomains.map((d) => `
      <div class="domain-section">
        <div class="domain-section-title">${escapeHtml(d)}<span class="hint" style="margin-left:8px;font-weight:400">${groups.get(d).length}</span></div>
        <div class="entity-cards">
          ${groups.get(d).sort((a, b) => a.friendly_name.localeCompare(b.friendly_name))
                  .map((ent) => renderEntityCard(ent)).join('')}
        </div>
      </div>
    `).join('')}
  `;

  document.getElementById('back-to-areas').addEventListener('click', () => {
    MAIN.currentAreaId = null;
    renderAreasGrid();
  });
  document.getElementById('refresh-area').addEventListener('click', () => loadMainData());
  wireAreaControls();
}

// -------------------------------------------------------------
// Per-entity control widgets — driven by attributes
// -------------------------------------------------------------
function renderEntityCard(entity) {
  const head = renderCardHeader(entity);
  const body = renderCardBody(entity);
  return `
    <div class="entity-control-card" data-entity="${escapeHtml(entity.entity_id)}">
      ${head}
      ${body ? `<div class="entity-control-body">${body}</div>` : ''}
    </div>
  `;
}

function renderCardHeader(entity) {
  const state = String(entity.state ?? '');
  const isOn = ['on', 'open', 'unlocked', 'playing', 'home', 'active', 'cleaning'].includes(state);
  const isOff = ['off', 'closed', 'locked', 'idle', 'standby', 'not_home', 'docked'].includes(state);
  const togglable = new Set(['light', 'switch', 'input_boolean', 'fan', 'lock', 'cover', 'media_player', 'automation']);
  const runnable  = new Set(['scene', 'script']);

  let control;
  if (togglable.has(entity.domain)) {
    control = `<button class="toggle-btn ${isOn ? 'on' : 'off'}" data-action="toggle">${isOn ? 'ON' : 'OFF'}</button>`;
  } else if (runnable.has(entity.domain)) {
    control = `<button class="btn" data-action="${entity.domain === 'scene' ? 'activate_scene' : 'run_script'}">Run</button>`;
  } else {
    const cls = isOn ? 'on' : isOff ? 'off' : '';
    const unit = (entity.attributes || {}).unit_of_measurement || '';
    control = `<span class="state-pill ${cls}">${escapeHtml(state)}${unit ? ' ' + escapeHtml(unit) : ''}</span>`;
  }

  return `
    <div class="entity-control-head">
      <div class="entity-control-meta">
        <div class="entity-control-name">${escapeHtml(entity.friendly_name)}</div>
        <div class="entity-control-id">${escapeHtml(entity.entity_id)}</div>
      </div>
      ${control}
    </div>
  `;
}

function renderCardBody(entity) {
  switch (entity.domain) {
    case 'light':        return renderLight(entity);
    case 'climate':      return renderClimate(entity);
    case 'cover':        return renderCover(entity);
    case 'fan':          return renderFan(entity);
    case 'media_player': return renderMediaPlayer(entity);
    case 'vacuum':       return renderVacuum(entity);
    case 'sensor':
    case 'binary_sensor':
    case 'weather':
    case 'sun':
    case 'person':
    case 'device_tracker':
      return renderSensorDetails(entity);
    default:
      return '';
  }
}

// ----- Light -------------------------------------------------------------
function renderLight(entity) {
  const attrs = entity.attributes || {};
  const modes = attrs.supported_color_modes || [];
  const hasDim = modes.some((m) => ['brightness', 'color_temp', 'hs', 'rgb', 'rgbw', 'rgbww', 'xy', 'white'].includes(m));
  const hasCt = modes.includes('color_temp');
  const hasColor = modes.some((m) => ['hs', 'rgb', 'rgbw', 'rgbww', 'xy'].includes(m));
  const effects = attrs.effect_list || [];
  let html = '';

  if (hasDim) {
    const bri = attrs.brightness || 0;
    const pct = Math.round((bri / 255) * 100);
    html += rangeControl('brightness_pct', 'Brightness', 0, 100, 1, pct, '%');
  }
  if (hasCt) {
    const k = attrs.color_temp_kelvin || attrs.color_temp || 3000;
    const minK = attrs.min_color_temp_kelvin || 2000;
    const maxK = attrs.max_color_temp_kelvin || 6500;
    html += rangeControl('kelvin', 'Color temperature', minK, maxK, 10, k, 'K');
  }
  if (hasColor) {
    const rgb = attrs.rgb_color || [255, 255, 255];
    const hex = '#' + rgb.map((v) => Math.min(255, Math.max(0, v|0)).toString(16).padStart(2, '0')).join('');
    html += `
      <div class="ctrl-row">
        <label class="ctrl-row-label">Color</label>
        <input type="color" value="${hex}" data-action="rgb_color" style="width:60px;height:32px;padding:2px;border-radius:6px;background:transparent" />
      </div>
    `;
  }
  if (effects.length) {
    html += `
      <div class="ctrl-row">
        <label class="ctrl-row-label">Effect</label>
        <select data-action="effect">
          <option value="">— none —</option>
          ${effects.map((e) => `<option value="${escapeHtml(e)}" ${attrs.effect === e ? 'selected' : ''}>${escapeHtml(e)}</option>`).join('')}
        </select>
      </div>
    `;
  }
  return html;
}

// ----- Climate -----------------------------------------------------------
function renderClimate(entity) {
  const attrs = entity.attributes || {};
  const hvacModes = attrs.hvac_modes || [];
  const fanModes  = attrs.fan_modes  || [];
  const presets   = attrs.preset_modes || [];
  const swing     = attrs.swing_modes || [];
  const minT = attrs.min_temp ?? 7;
  const maxT = attrs.max_temp ?? 35;
  const step = attrs.target_temp_step ?? 0.5;
  const target = attrs.temperature ?? minT;
  const current = attrs.current_temperature;
  const unit = attrs.temperature_unit || '°C';
  let html = '';

  if (hvacModes.length) {
    html += selectControl('hvac_mode', 'HVAC mode', hvacModes, entity.state);
  }
  html += rangeControl('temperature', `Target ${current !== undefined ? `(now ${current}${unit})` : ''}`, minT, maxT, step, target, unit);
  if (fanModes.length) html += selectControl('fan_mode', 'Fan mode', fanModes, attrs.fan_mode);
  if (presets.length)  html += selectControl('preset_mode', 'Preset', presets, attrs.preset_mode);
  if (swing.length)    html += selectControl('swing_mode', 'Swing', swing, attrs.swing_mode);
  return html;
}

// ----- Cover -------------------------------------------------------------
const COVER_FEATURES = { OPEN: 1, CLOSE: 2, SET_POSITION: 4, STOP: 8, OPEN_TILT: 16, CLOSE_TILT: 32, STOP_TILT: 64, SET_TILT_POSITION: 128 };
function renderCover(entity) {
  const attrs = entity.attributes || {};
  const f = attrs.supported_features || 0;
  const pos = attrs.current_position;
  let html = '<div class="ctrl-row-buttons">';
  if (f & COVER_FEATURES.OPEN)  html += `<button class="btn secondary" data-action="open_cover">↑ Open</button>`;
  if (f & COVER_FEATURES.STOP)  html += `<button class="btn secondary" data-action="stop_cover">⏸ Stop</button>`;
  if (f & COVER_FEATURES.CLOSE) html += `<button class="btn secondary" data-action="close_cover">↓ Close</button>`;
  html += '</div>';
  if (f & COVER_FEATURES.SET_POSITION) {
    html += rangeControl('set_cover_position', 'Position', 0, 100, 1, pos ?? 0, '%');
  }
  return html;
}

// ----- Fan ---------------------------------------------------------------
function renderFan(entity) {
  const attrs = entity.attributes || {};
  const pct = attrs.percentage ?? 0;
  const presets = attrs.preset_modes || [];
  let html = rangeControl('percentage', 'Speed', 0, 100, attrs.percentage_step || 1, pct, '%');
  if (presets.length) html += selectControl('preset_mode_fan', 'Preset', presets, attrs.preset_mode);
  if (attrs.oscillating !== undefined) {
    html += `
      <div class="ctrl-row">
        <label class="ctrl-row-label">Oscillating</label>
        <select data-action="oscillate">
          <option value="true"  ${attrs.oscillating ? 'selected' : ''}>true</option>
          <option value="false" ${!attrs.oscillating ? 'selected' : ''}>false</option>
        </select>
      </div>
    `;
  }
  return html;
}

// ----- Media Player ------------------------------------------------------
function renderMediaPlayer(entity) {
  const attrs = entity.attributes || {};
  const vol = Math.round((attrs.volume_level || 0) * 100);
  const sources = attrs.source_list || [];
  let html = `
    <div class="ctrl-row-buttons">
      <button class="btn secondary" data-action="media_previous_track">⏮</button>
      <button class="btn secondary" data-action="media_play_pause">⏯</button>
      <button class="btn secondary" data-action="media_next_track">⏭</button>
      <button class="btn secondary" data-action="media_stop">⏹</button>
    </div>
  `;
  html += rangeControl('volume_level', 'Volume', 0, 100, 1, vol, '%');
  if (sources.length) html += selectControl('select_source', 'Source', sources, attrs.source);
  return html;
}

// ----- Vacuum ------------------------------------------------------------
function renderVacuum(entity) {
  const attrs = entity.attributes || {};
  const speeds = attrs.fan_speed_list || [];
  let html = `
    <div class="ctrl-row-buttons">
      <button class="btn secondary" data-action="vacuum_start">▶ Start</button>
      <button class="btn secondary" data-action="vacuum_pause">⏸ Pause</button>
      <button class="btn secondary" data-action="vacuum_stop">⏹ Stop</button>
      <button class="btn secondary" data-action="vacuum_return_to_base">🏠 Dock</button>
      <button class="btn secondary" data-action="vacuum_locate">📍 Locate</button>
    </div>
  `;
  if (speeds.length) html += selectControl('vacuum_fan_speed', 'Fan speed', speeds, attrs.fan_speed);
  return html;
}

// ----- Sensors (read-only) -----------------------------------------------
function renderSensorDetails(entity) {
  const attrs = entity.attributes || {};
  const unit = attrs.unit_of_measurement || '';
  const interesting = ['device_class', 'state_class', 'battery_level', 'last_reset'];
  const rows = interesting
    .filter((k) => attrs[k] !== undefined)
    .map((k) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(String(attrs[k]))}</td></tr>`)
    .join('');
  return `
    <div class="sensor-big-state">${escapeHtml(String(entity.state))}${unit ? ` <span class="sensor-unit">${escapeHtml(unit)}</span>` : ''}</div>
    ${rows ? `<table class="kv-table" style="margin-top:8px">${rows}</table>` : ''}
  `;
}

// ----- Reusable widgets --------------------------------------------------
function rangeControl(action, label, min, max, step, value, unit) {
  return `
    <div class="ctrl-row">
      <label class="ctrl-row-label">${escapeHtml(label)}</label>
      <div class="range-with-value">
        <input type="range" min="${min}" max="${max}" step="${step}" value="${value}" data-action="${escapeHtml(action)}" data-unit="${escapeHtml(unit || '')}" />
        <span class="val">${value}${escapeHtml(unit || '')}</span>
      </div>
    </div>
  `;
}

function selectControl(action, label, options, current) {
  return `
    <div class="ctrl-row">
      <label class="ctrl-row-label">${escapeHtml(label)}</label>
      <select data-action="${escapeHtml(action)}">
        ${options.map((o) => `<option value="${escapeHtml(o)}" ${o === current ? 'selected' : ''}>${escapeHtml(o)}</option>`).join('')}
      </select>
    </div>
  `;
}

// -------------------------------------------------------------
// Wire control interactions
// -------------------------------------------------------------
function wireAreaControls() {
  const content = document.getElementById('sh-content');
  if (!content) return;

  // Live update slider value label while dragging.
  content.addEventListener('input', (e) => {
    const inp = e.target;
    if (inp.type === 'range' && inp.dataset.action) {
      const val = inp.parentElement?.querySelector('.val');
      if (val) val.textContent = `${inp.value}${inp.dataset.unit || ''}`;
    }
  });

  // Service-call on settled change.
  content.addEventListener('change', async (e) => {
    const inp = e.target;
    if (!inp.dataset.action) return;
    const card = inp.closest('.entity-control-card');
    if (!card) return;
    await invokeEntityAction(card.dataset.entity, inp.dataset.action, inp.value);
  });

  // Button clicks (toggle, transports, run, etc).
  content.addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;
    const card = btn.closest('.entity-control-card');
    if (!card) return;
    await invokeEntityAction(card.dataset.entity, btn.dataset.action, null);
  });
}

async function invokeEntityAction(entityId, action, value) {
  const entity = MAIN.entityById.get(entityId);
  if (!entity) return;
  const d = entity.domain;
  let call;

  switch (action) {
    case 'toggle': {
      let svc;
      if      (d === 'lock')          svc = entity.state === 'locked'  ? 'unlock'     : 'lock';
      else if (d === 'cover')         svc = entity.state === 'closed'  ? 'open_cover' : 'close_cover';
      else if (d === 'media_player')  svc = entity.state === 'playing' ? 'media_pause': 'media_play';
      else if (d === 'automation')    svc = entity.state === 'on'      ? 'turn_off'   : 'turn_on';
      else                            svc = entity.state === 'on'      ? 'turn_off'   : 'turn_on';
      call = [d, svc, { entity_id: entityId }];
      break;
    }
    case 'brightness_pct':  call = ['light', 'turn_on', { entity_id: entityId, brightness_pct: +value }]; break;
    case 'kelvin':          call = ['light', 'turn_on', { entity_id: entityId, kelvin: +value }]; break;
    case 'rgb_color': {
      const hex = value;
      const rgb = [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)];
      call = ['light', 'turn_on', { entity_id: entityId, rgb_color: rgb }];
      break;
    }
    case 'effect': {
      const data = { entity_id: entityId };
      if (value) data.effect = value;
      call = ['light', 'turn_on', data];
      break;
    }
    case 'hvac_mode':       call = ['climate', 'set_hvac_mode',   { entity_id: entityId, hvac_mode: value }]; break;
    case 'temperature':     call = ['climate', 'set_temperature', { entity_id: entityId, temperature: parseFloat(value) }]; break;
    case 'fan_mode':        call = ['climate', 'set_fan_mode',    { entity_id: entityId, fan_mode: value }]; break;
    case 'preset_mode':     call = ['climate', 'set_preset_mode', { entity_id: entityId, preset_mode: value }]; break;
    case 'swing_mode':      call = ['climate', 'set_swing_mode',  { entity_id: entityId, swing_mode: value }]; break;

    case 'open_cover':
    case 'close_cover':
    case 'stop_cover':         call = ['cover', action, { entity_id: entityId }]; break;
    case 'set_cover_position': call = ['cover', 'set_cover_position', { entity_id: entityId, position: +value }]; break;

    case 'percentage':       call = ['fan', 'set_percentage',  { entity_id: entityId, percentage: +value }]; break;
    case 'oscillate':        call = ['fan', 'oscillate',       { entity_id: entityId, oscillating: value === 'true' }]; break;
    case 'preset_mode_fan':  call = ['fan', 'set_preset_mode', { entity_id: entityId, preset_mode: value }]; break;

    case 'media_play':
    case 'media_pause':
    case 'media_play_pause':
    case 'media_stop':
    case 'media_next_track':
    case 'media_previous_track':  call = ['media_player', action, { entity_id: entityId }]; break;
    case 'volume_level':          call = ['media_player', 'volume_set',  { entity_id: entityId, volume_level: (+value) / 100 }]; break;
    case 'select_source':         call = ['media_player', 'select_source',{ entity_id: entityId, source: value }]; break;

    case 'vacuum_start':            call = ['vacuum', 'start',          { entity_id: entityId }]; break;
    case 'vacuum_pause':            call = ['vacuum', 'pause',          { entity_id: entityId }]; break;
    case 'vacuum_stop':             call = ['vacuum', 'stop',           { entity_id: entityId }]; break;
    case 'vacuum_return_to_base':   call = ['vacuum', 'return_to_base', { entity_id: entityId }]; break;
    case 'vacuum_locate':           call = ['vacuum', 'locate',         { entity_id: entityId }]; break;
    case 'vacuum_fan_speed':        call = ['vacuum', 'set_fan_speed',  { entity_id: entityId, fan_speed: value }]; break;

    case 'activate_scene':  call = ['scene',  'turn_on', { entity_id: entityId }]; break;
    case 'run_script':      call = ['script', 'turn_on', { entity_id: entityId }]; break;

    default:
      console.warn('No handler for action', action);
      return;
  }

  try {
    await HA.call(call[0], call[1], call[2]);
    await refreshEntityInPlace(entityId);
  } catch (e) {
    console.error('action failed:', e);
  }
}

async function refreshEntityInPlace(entityId) {
  try {
    const fresh = await HA.getEntity(entityId);
    MAIN.entityById.set(entityId, fresh);
    // Also patch into the current area's list so subsequent renders are consistent.
    for (const a of MAIN.areas) {
      const idx = a.entities.findIndex((e) => e.entity_id === entityId);
      if (idx >= 0) a.entities[idx] = fresh;
    }
    const card = document.querySelector(`.entity-control-card[data-entity="${cssEsc(entityId)}"]`);
    if (card) {
      const wrap = document.createElement('div');
      wrap.innerHTML = renderEntityCard(fresh);
      card.replaceWith(wrap.firstElementChild);
    }
  } catch { /* ignore */ }
}

function cssEsc(s) { return String(s).replace(/"/g, '\\"'); }

async function renderLiveAgent(root) {
  // Gate on Gemini API key being set.
  let cfg;
  try { cfg = await LiveAgent.getConfig(); }
  catch (e) {
    root.innerHTML = `<div class="empty-state"><h3>Backend error</h3><p>${escapeHtml(e.message)}</p></div>`;
    return;
  }

  if (!cfg.api_key_set) {
    root.innerHTML = `
      <div class="page-header">
        <h1>Smart Home · Live Agent</h1>
        <p>Natural-language control over Home Assistant via the Gemini Live API.</p>
      </div>
      <div class="empty-state">
        <h3>API key required</h3>
        <p>Paste your Google AI Studio API key in <a href="#/settings">Settings → Gemini Live Agent</a> to get started.</p>
      </div>
    `;
    return;
  }

  root.innerHTML = `
    <div class="page-header">
      <h1>Smart Home · Live Agent</h1>
      <p>Talk to Gemini in real time. Optionally pick a Frigate camera — the agent will see frames every ~1.5s and can answer questions about it. Tool calls to Home Assistant happen on the backend.</p>
    </div>

    <div class="split">
      <div class="card" style="margin:0">
        <h2>Camera</h2>
        <label class="field">
          <span class="lbl">Source</span>
          <select id="live-camera"><option value="">No camera</option></select>
        </label>
        <div class="live-frame" style="margin-top:8px">
          <img id="live-camera-img" alt="" />
        </div>
        <p class="hint" style="margin-top:8px">Snapshots refresh in the UI (1 s) and stream to the agent (1.5 s).</p>
      </div>

      <div class="card" style="margin:0">
        <h2>Session</h2>
        <div class="status-pill" style="margin-bottom:12px">
          <span class="status-dot" id="live-dot"></span>
          <span class="status-label">Gemini:</span>
          <span class="status-text" id="live-status-text">Not connected</span>
        </div>

        <div class="btn-row" style="margin-bottom:10px">
          <button class="btn" id="btn-live-start">Start Session</button>
          <button class="btn secondary" id="btn-live-stop" disabled>Stop Session</button>
          <button class="btn secondary" id="btn-mute" disabled>🎤 Listening</button>
        </div>

        <div class="mic-meter-row">
          <span class="mic-meter-label">Mic</span>
          <div class="mic-meter">
            <div class="mic-meter-bar" id="mic-meter-bar"></div>
            <div class="mic-meter-peak" id="mic-meter-peak"></div>
          </div>
        </div>

        <label class="agent-toggle">
          <input type="checkbox" id="only-areas-toggle" />
          <span>Only consider entities in HA <strong>Areas</strong></span>
        </label>

        <details class="wake-words">
          <summary>Wake / stop words (optional)</summary>
          <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
            <label class="field" style="flex:1;min-width:160px;margin:0">
              <span class="lbl">Activate when I say</span>
              <input type="text" id="wake-word" placeholder="hey assistant" />
            </label>
            <label class="field" style="flex:1;min-width:160px;margin:0">
              <span class="lbl">Mute when I say</span>
              <input type="text" id="stop-word" placeholder="goodbye" />
            </label>
          </div>
          <p class="hint" style="margin-top:8px">
            If a wake word is set, the session starts muted until you say it.
            Leave both blank for always-on listening.
          </p>
        </details>

        <label class="field">
          <span class="lbl">Type a message</span>
          <div style="display:flex;gap:6px">
            <input type="text" id="live-text-input" placeholder="ask anything, or instruct the agent" />
            <button class="btn secondary" id="btn-live-send">Send</button>
          </div>
        </label>

        <h3 style="margin:16px 0 6px;font-size:13px">Conversation log</h3>
        <div class="log-box" id="live-log" style="max-height:340px"></div>
      </div>
    </div>
  `;

  const camSel = document.getElementById('live-camera');
  const camImg = document.getElementById('live-camera-img');

  // Populate cameras (best-effort).
  Frigate.getCameras().then((cams) => {
    cams.forEach((c) => {
      const opt = document.createElement('option');
      opt.value = c.name; opt.textContent = c.name;
      camSel.appendChild(opt);
    });
  }).catch(() => { /* Frigate may not be configured */ });

  // Live preview ticker.
  let previewTimer = null;
  function refreshPreview() {
    const name = camSel.value;
    if (!name) { camImg.removeAttribute('src'); return; }
    camImg.src = `/api/frigate/snapshot/${encodeURIComponent(name)}?h=400&cb=${Date.now()}`;
  }
  function startPreview() {
    stopPreview();
    refreshPreview();
    previewTimer = setInterval(refreshPreview, 1000);
  }
  function stopPreview() {
    if (previewTimer) clearInterval(previewTimer);
    previewTimer = null;
  }

  camSel.addEventListener('change', () => {
    refreshPreview();
    if (camSel.value) startPreview(); else stopPreview();
    if (window.LiveAgentSession) window.LiveAgentSession.setCamera(camSel.value || null);
  });

  document.getElementById('btn-live-start').addEventListener('click', async () => {
    const startBtn = document.getElementById('btn-live-start');
    const stopBtn  = document.getElementById('btn-live-stop');
    const muteBtn  = document.getElementById('btn-mute');
    startBtn.disabled = true;
    try {
      await window.LiveAgentSession.start({
        camera: camSel.value || null,
        log: document.getElementById('live-log'),
        wakeWord: document.getElementById('wake-word').value,
        stopWord: document.getElementById('stop-word').value,
        onlyAreas: document.getElementById('only-areas-toggle').checked,
      });
      stopBtn.disabled = false;
      // Mute only makes sense when a mic is actually attached to the session.
      muteBtn.disabled = !window.LiveAgentSession.hasMic();
      if (camSel.value) startPreview();
    } catch (e) {
      startBtn.disabled = false;
    }
  });

  document.getElementById('btn-live-stop').addEventListener('click', () => {
    window.LiveAgentSession.stop();
    stopPreview();
  });

  document.getElementById('btn-mute').addEventListener('click', () => {
    window.LiveAgentSession.setMuted(!window.LiveAgentSession.isMuted());
  });

  // Toggle "only-areas" can be flipped before *and* during a session.
  // If a session is active, setOnlyAreas pushes a config message to the
  // backend immediately so the next tool call uses the new filter.
  document.getElementById('only-areas-toggle').addEventListener('change', (e) => {
    window.LiveAgentSession.setOnlyAreas(e.target.checked);
  });

  const textInput = document.getElementById('live-text-input');
  const sendText = () => {
    const t = textInput.value.trim();
    if (!t) return;
    window.LiveAgentSession.sendText(t);
    textInput.value = '';
  };
  document.getElementById('btn-live-send').addEventListener('click', sendText);
  textInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendText(); });
}

// ----- Test page ---------------------------------------------------------
const testPageState = {
  knowledge: null,
  entities: [],
  selected: null,
  domains: [],
};

async function renderSmartHomeTest(root) {
  // Gate on HA being configured.
  let cfg;
  try {
    cfg = await HA.getConfig();
  } catch (e) {
    root.innerHTML = `<div class="empty-state"><h3>Backend error</h3><p>${escapeHtml(e.message)}</p></div>`;
    return;
  }
  if (!cfg.url || !cfg.token_set) {
    root.innerHTML = `
      <div class="page-header">
        <h1>Smart Home · Test</h1>
        <p>List and control Home Assistant entities directly.</p>
      </div>
      <div class="empty-state">
        <h3>Home Assistant not configured</h3>
        <p>Add your HA URL and token in <a href="#/settings">Settings</a> to load entities.</p>
      </div>
    `;
    return;
  }

  root.innerHTML = `
    <div class="page-header">
      <h1>Smart Home · Test</h1>
      <p>Pick an entity to inspect its state and drive its services. Domain-aware controls come from the shared capabilities catalog.</p>
    </div>

    <div class="card">
      <div class="filter-bar">
        <label class="field">
          <span class="lbl">Search</span>
          <input type="text" id="ent-search" placeholder="kitchen, switch, sensor.outside_temperature…" />
        </label>
        <label class="field">
          <span class="lbl">Domain</span>
          <select id="ent-domain"><option value="">All domains</option></select>
        </label>
        <div class="filter-actions">
          <button class="btn secondary" id="btn-reload">Reload</button>
        </div>
      </div>
    </div>

    <div class="split">
      <div class="card" style="margin:0">
        <div class="events-meta">
          <h2 style="margin:0">Entities</h2>
          <span class="count" id="ent-count"></span>
        </div>
        <div id="entity-list-wrap"><p class="hint">Loading…</p></div>
      </div>

      <div class="card" style="margin:0">
        <h2>Selected entity</h2>
        <div id="entity-detail"><p class="hint">Pick an entity on the left.</p></div>
      </div>
    </div>
  `;

  document.getElementById('ent-search').addEventListener('input', renderEntityList);
  document.getElementById('ent-domain').addEventListener('change', renderEntityList);
  document.getElementById('btn-reload').addEventListener('click', loadTestData);

  loadTestData();
}

async function loadTestData() {
  const wrap = document.getElementById('entity-list-wrap');
  if (wrap) wrap.innerHTML = `<p class="hint">Loading…</p>`;
  try {
    const [knowledge, domains, entities] = await Promise.all([
      testPageState.knowledge ? Promise.resolve(testPageState.knowledge) : HA.getKnowledge(),
      HA.getDomains(),
      HA.getEntities(),
    ]);
    testPageState.knowledge = knowledge;
    testPageState.domains = domains;
    testPageState.entities = entities;

    const sel = document.getElementById('ent-domain');
    const current = sel.value;
    sel.innerHTML = `<option value="">All domains (${entities.length})</option>` +
      domains.map((d) => `<option value="${escapeHtml(d.domain)}">${escapeHtml(d.domain)} (${d.count})</option>`).join('');
    sel.value = current;

    renderEntityList();
  } catch (e) {
    if (wrap) wrap.innerHTML = `<p class="hint" style="color:var(--err)">Failed to load: ${escapeHtml(e.message)}</p>`;
  }
}

function renderEntityList() {
  const wrap = document.getElementById('entity-list-wrap');
  const countEl = document.getElementById('ent-count');
  if (!wrap) return;
  const q = (document.getElementById('ent-search')?.value || '').toLowerCase().trim();
  const dom = document.getElementById('ent-domain')?.value || '';

  let entities = testPageState.entities;
  if (dom) entities = entities.filter((e) => e.domain === dom);
  if (q) {
    entities = entities.filter((e) =>
      e.entity_id.toLowerCase().includes(q) ||
      (e.friendly_name || '').toLowerCase().includes(q)
    );
  }

  countEl.textContent = `${entities.length} of ${testPageState.entities.length}`;

  if (entities.length === 0) {
    wrap.innerHTML = `<p class="hint">No entities match.</p>`;
    return;
  }

  wrap.innerHTML = `
    <div class="entity-list">
      ${entities.slice(0, 500).map((e) => `
        <div class="entity-row${testPageState.selected?.entity_id === e.entity_id ? ' active' : ''}" data-id="${escapeHtml(e.entity_id)}">
          <div class="entity-name"><span class="domain-chip">${escapeHtml(e.domain)}</span>${escapeHtml(e.friendly_name)}</div>
          <div class="entity-id">${escapeHtml(e.entity_id)}</div>
          <div class="entity-state-mini">state: ${escapeHtml(String(e.state))}</div>
        </div>
      `).join('')}
      ${entities.length > 500 ? `<div class="entity-row" style="cursor:default;color:var(--text-dim);font-size:11px">Showing first 500. Refine the search to see more.</div>` : ''}
    </div>
  `;

  wrap.querySelectorAll('.entity-row[data-id]').forEach((row) => {
    row.addEventListener('click', () => selectEntity(row.dataset.id));
  });
}

async function selectEntity(entityId) {
  const ent = testPageState.entities.find((e) => e.entity_id === entityId);
  if (!ent) return;
  testPageState.selected = ent;
  document.querySelectorAll('.entity-row').forEach((r) => r.classList.toggle('active', r.dataset.id === entityId));
  renderEntityDetail();

  // Refresh just this entity in the background so its state is current.
  try {
    const fresh = await HA.getEntity(entityId);
    testPageState.selected = fresh;
    // Keep the cached list updated too.
    const idx = testPageState.entities.findIndex((e) => e.entity_id === entityId);
    if (idx >= 0) testPageState.entities[idx] = fresh;
    renderEntityDetail();
  } catch {
    /* keep showing cached state */
  }
}

function renderEntityDetail() {
  const detail = document.getElementById('entity-detail');
  const ent = testPageState.selected;
  if (!detail) return;
  if (!ent) {
    detail.innerHTML = `<p class="hint">Pick an entity on the left.</p>`;
    return;
  }

  const domainCap = testPageState.knowledge?.domains?.[ent.domain] || null;
  const readOnly = domainCap?.read_only === true || (domainCap?.services && Object.keys(domainCap.services).length === 0);

  const state = ent.state;
  const isOnish = ['on', 'open', 'unlocked', 'home', 'playing', 'active'].includes(String(state));
  const isOffish = ['off', 'closed', 'locked', 'not_home', 'idle', 'standby'].includes(String(state));
  const statePill = `<span class="state-pill ${isOnish ? 'on' : isOffish ? 'off' : ''}">${escapeHtml(String(state))}</span>`;

  const attrs = ent.attributes || {};
  const attrRows = Object.entries(attrs).slice(0, 40).map(([k, v]) => `
    <tr><td>${escapeHtml(k)}</td><td>${escapeHtml(formatAttrValue(v))}</td></tr>
  `).join('');

  const controlsHtml = readOnly
    ? `<p class="hint">This entity is read-only (domain <code>${escapeHtml(ent.domain)}</code>).</p>`
    : buildControlsHtml(ent, domainCap);

  detail.innerHTML = `
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
      <span class="domain-chip">${escapeHtml(ent.domain)}</span>
      <strong>${escapeHtml(ent.friendly_name)}</strong>
      ${statePill}
    </div>
    <div class="entity-id" style="margin-bottom:12px">${escapeHtml(ent.entity_id)}</div>

    <h3 style="margin:14px 0 6px;font-size:13px">Controls</h3>
    ${controlsHtml}

    <h3 style="margin:18px 0 6px;font-size:13px">Attributes</h3>
    <table class="kv-table">
      <tbody>
        <tr><td>state</td><td>${escapeHtml(String(state))}</td></tr>
        ${attrRows}
        <tr><td>last_changed</td><td>${escapeHtml(ent.last_changed || '')}</td></tr>
        <tr><td>last_updated</td><td>${escapeHtml(ent.last_updated || '')}</td></tr>
      </tbody>
    </table>

    <h3 style="margin:18px 0 6px;font-size:13px">Call log</h3>
    <div class="log-box" id="call-log"></div>
  `;

  wireEntityControls(ent, domainCap);
}

function formatAttrValue(v) {
  if (v === null || v === undefined) return '';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

// Build per-domain control widgets from the capabilities catalog.
function buildControlsHtml(ent, cap) {
  if (!cap || !cap.services) {
    return `<p class="hint">No control catalog for domain <code>${escapeHtml(ent.domain)}</code>.</p>`;
  }
  const services = Object.entries(cap.services).filter(([name]) => name !== '*');
  if (services.length === 0) {
    return `<p class="hint">No services registered for this domain.</p>`;
  }
  return `<div class="controls-grid">${services.map(([svc, def]) => renderServiceControl(ent, svc, def)).join('')}</div>`;
}

function renderServiceControl(ent, svc, def) {
  const params = def.params || [];
  const inputs = params.map((p) => renderParamInput(svc, p)).join('');
  return `
    <div class="control-row" data-service="${escapeHtml(svc)}">
      <div class="ctrl-title">${escapeHtml(svc)}</div>
      <div class="ctrl-desc">${escapeHtml(def.description || '')}</div>
      <div class="ctrl-inputs">${inputs}</div>
      <div><button class="btn" data-call="${escapeHtml(svc)}">Call</button></div>
    </div>
  `;
}

function renderParamInput(svc, p) {
  // Every param gets an opt-in checkbox. Required params start checked.
  // The widget is disabled when the checkbox is off so it's visually obvious
  // that nothing will be sent for that field.
  const id = `p-${svc}-${p.name}`;
  const required = p.optional !== true;
  const checked = required ? 'checked' : '';
  const disAttr = required ? '' : 'disabled';
  const labelText = `${escapeHtml(p.name)}${p.optional ? ' (optional)' : ''}`;
  const useChk = `<input type="checkbox" class="param-use" data-target="${id}" ${checked} />`;
  const label = `<span class="lbl" style="display:flex;align-items:center;gap:6px;cursor:pointer">${useChk}<span>${labelText}</span></span>`;
  const desc = p.description ? `<span class="hint" style="font-size:11px">${escapeHtml(p.description)}</span>` : '';

  if (p.type === 'bool') {
    return `
      <label class="field" style="margin:0">
        ${label}
        <select id="${id}" data-pname="${escapeHtml(p.name)}" data-ptype="bool" ${disAttr}>
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
        ${desc}
      </label>
    `;
  }
  if (p.choices) {
    return `
      <label class="field" style="margin:0">
        ${label}
        <select id="${id}" data-pname="${escapeHtml(p.name)}" data-ptype="string" ${disAttr}>
          ${p.choices.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('')}
        </select>
        ${desc}
      </label>
    `;
  }
  if (p.type === 'int' || p.type === 'float') {
    const min = p.range?.[0] ?? '';
    const max = p.range?.[1] ?? '';
    const step = p.type === 'int' ? 1 : 'any';
    if (p.range) {
      const initial = Math.round((p.range[0] + p.range[1]) / 2);
      return `
        <label class="field" style="margin:0">
          ${label}
          <div class="range-with-value">
            <input type="range" id="${id}" data-pname="${escapeHtml(p.name)}" data-ptype="${p.type}"
                   min="${min}" max="${max}" step="${step}" value="${initial}" ${disAttr}
                   oninput="this.nextElementSibling.textContent=this.value" />
            <span class="val">${initial}</span>
          </div>
          ${desc}
        </label>
      `;
    }
    return `
      <label class="field" style="margin:0">
        ${label}
        <input type="number" id="${id}" data-pname="${escapeHtml(p.name)}" data-ptype="${p.type}" step="${step}" ${disAttr} />
        ${desc}
      </label>
    `;
  }
  if (p.type === 'color_rgb') {
    return `
      <label class="field" style="margin:0">
        ${label}
        <input type="color" id="${id}" data-pname="${escapeHtml(p.name)}" data-ptype="color_rgb" value="#ffffff" ${disAttr}
               style="width:60px;height:36px;padding:2px;border-radius:6px;background:transparent" />
        ${desc}
      </label>
    `;
  }
  // string / list / dict fallback
  return `
    <label class="field" style="margin:0">
      ${label}
      <input type="text" id="${id}" data-pname="${escapeHtml(p.name)}" data-ptype="${escapeHtml(p.type)}" ${disAttr} />
      ${desc}
    </label>
  `;
}

function wireEntityControls(ent, cap) {
  // Toggle checkboxes enable/disable their target input.
  document.querySelectorAll('.param-use').forEach((chk) => {
    chk.addEventListener('change', () => {
      const target = document.getElementById(chk.dataset.target);
      if (target) target.disabled = !chk.checked;
    });
  });

  document.querySelectorAll('.control-row [data-call]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const row = btn.closest('.control-row');
      const svc = row.dataset.service;
      const data = { entity_id: ent.entity_id };

      row.querySelectorAll('[data-pname]').forEach((inp) => {
        // Skip params whose opt-in checkbox is off.
        const chk = row.querySelector(`.param-use[data-target="${inp.id}"]`);
        if (chk && !chk.checked) return;

        const name = inp.dataset.pname;
        const type = inp.dataset.ptype;
        const raw = inp.value;
        if (raw === '' || raw === null || raw === undefined) return;
        if (type === 'bool')        data[name] = (raw === 'true');
        else if (type === 'int')    data[name] = parseInt(raw, 10);
        else if (type === 'float')  data[name] = parseFloat(raw);
        else if (type === 'color_rgb') data[name] = hexToRgb(raw);
        else                        data[name] = raw;
      });

      logCall(`→ ${ent.domain}.${svc} ${JSON.stringify(data)}`);
      btn.disabled = true;
      try {
        await HA.call(ent.domain, svc, data);
        logCall(`✓ ok`, 'ok');
        setTimeout(() => selectEntity(ent.entity_id), 400);
      } catch (e) {
        logCall(`✗ ${e.message}`, 'err');
      } finally {
        btn.disabled = false;
      }
    });
  });
}

function hexToRgb(hex) {
  const h = hex.replace('#', '');
  return [
    parseInt(h.substring(0, 2), 16),
    parseInt(h.substring(2, 4), 16),
    parseInt(h.substring(4, 6), 16),
  ];
}

function logCall(msg, kind) {
  const log = document.getElementById('call-log');
  if (!log) return;
  const line = document.createElement('div');
  line.className = `log-line${kind ? ' ' + kind : ''}`;
  const ts = new Date().toLocaleTimeString();
  line.textContent = `[${ts}] ${msg}`;
  log.prepend(line);
}

// =============================================================
// AI-Camera pages
// =============================================================
function renderAiCameraMain(root) {
  root.innerHTML = `
    <div class="page-header">
      <h1>AI-Camera</h1>
      <p>Vision-driven rules over your Frigate cameras.</p>
    </div>
    <div class="empty-state">
      <h3>Main · coming soon</h3>
      <p>Dashboard for promoted rules will live here.</p>
    </div>
  `;
}

// -------------------------------------------------------------
// AI-Camera · Rules — persistent rules + history + alarm broadcast
// -------------------------------------------------------------
const RULES_STATE = {
  rules: [],
  expanded: new Set(),          // rule IDs currently showing their history panel
  pagination: {},               // rule_id -> { triggers: {offset,total,items}, iterations: {...} }
  cameras: [],
  haEntities: [],
  evtListener: null,
  // Motion (push-based from Frigate via MQTT bridge) — blinks camera badges
  // for rules whose scan mode reacts to motion.
  motion: {},                   // camera -> { motion: bool, objects: [...] }
  motionWs: null,
  motionReconnect: null,
  // Server-pushed countdown snapshots, keyed by rule_id. Only periodic /
  // periodic_motion rules populate this; other modes leave it untouched.
  countdowns: {},               // rule_id -> { remaining_s, total_s, paused, waiting_for_motion }
};

async function renderAiCameraRules(root) {
  // Same preflight as Playground — Rules need Frigate + Gemini.
  let frigateCfg, liveCfg;
  try {
    [frigateCfg, liveCfg] = await Promise.all([Frigate.getConfig(), LiveAgent.getConfig()]);
  } catch (e) {
    root.innerHTML = `<div class="empty-state"><h3>Backend error</h3><p>${escapeHtml(e.message)}</p></div>`;
    return;
  }
  if (!frigateCfg.url || !liveCfg.api_key_set) {
    root.innerHTML = `
      <div class="page-header"><h1>AI-Camera · Rules</h1></div>
      <div class="empty-state">
        <h3>Configure prerequisites</h3>
        <p>This page needs <strong>Frigate</strong> and a <strong>Gemini API key</strong>. Configure them in <a href="#/settings">Settings</a>.</p>
      </div>`;
    return;
  }

  root.innerHTML = `
    <div class="page-header">
      <h1>AI-Camera · Rules</h1>
      <p>Saved rules run continuously on the backend. Each rule analyses its cameras on the schedule you set; triggers are always stored, and you can optionally store every iteration too. Tick "Fire alarm" to flash a system-wide alarm banner with siren whenever the rule trips.</p>
    </div>
    <div class="card" style="margin:0">
      <div class="events-meta">
        <h2 style="margin:0">Rules</h2>
        <button class="btn" id="rules-new">+ New rule</button>
      </div>
      <div id="rules-list"><p class="hint">Loading…</p></div>
    </div>
  `;

  const [camsR, entsR] = await Promise.allSettled([Frigate.getCameras(), HA.getEntities()]);
  RULES_STATE.cameras = camsR.status === 'fulfilled' ? camsR.value : [];
  RULES_STATE.haEntities = entsR.status === 'fulfilled' ? entsR.value : [];
  await loadRules();
  renderRulesList();

  document.getElementById('rules-new').addEventListener('click', () => openRuleEditor(null));

  if (RULES_STATE.evtListener) window.removeEventListener('ai-camera-event', RULES_STATE.evtListener);
  RULES_STATE.evtListener = (e) => handleRulesEvent(e.detail);
  window.addEventListener('ai-camera-event', RULES_STATE.evtListener);

  document.getElementById('rules-list').addEventListener('click', onRulesListClick);
  ensureRulesMotionWs();
}

function tearDownRulesPage() {
  if (RULES_STATE.evtListener) {
    window.removeEventListener('ai-camera-event', RULES_STATE.evtListener);
    RULES_STATE.evtListener = null;
  }
  closeRulesMotionWs();
}

async function loadRules() {
  try {
    const r = await fetch('/api/ai-camera/rules');
    if (!r.ok) throw new Error(`http ${r.status}`);
    const data = await r.json();
    RULES_STATE.rules = data.rules || [];
  } catch (e) {
    RULES_STATE.rules = [];
  }
}

function renderRulesList() {
  const wrap = document.getElementById('rules-list');
  if (!wrap) return;
  if (RULES_STATE.rules.length === 0) {
    wrap.innerHTML = `<p class="hint">No rules yet. Click <strong>+ New rule</strong> to create one.</p>`;
    return;
  }
  wrap.innerHTML = RULES_STATE.rules.map(renderRuleRow).join('');
  wrap.querySelectorAll('[data-rule-action]').forEach((b) => b.addEventListener('click', onRuleAction));
  wrap.querySelectorAll('.rule-power[data-toggle-id]').forEach((btn) => btn.addEventListener('click', onTogglePower));
  // Re-mount detail panels for any rules that were expanded across re-renders.
  RULES_STATE.expanded.forEach((id) => {
    const rule = RULES_STATE.rules.find((r) => r.id === id);
    if (rule) renderHistoryFromCache(rule);
  });
  // Re-apply motion blink + last known countdown values for every row, since
  // the wholesale innerHTML replace just wiped them.
  refreshRulesMotion();
  refreshRulesAudioMeters();
  refreshRulesCountdowns();
}

function refreshRulesMotion() {
  document.querySelectorAll('.rule-row').forEach((row) => {
    const ruleId = row.dataset.ruleId;
    const mode = row.dataset.scanMode;
    const rule = RULES_STATE.rules.find((r) => r.id === ruleId);
    if (!rule) return;
    const motionMode = mode === 'motion' || mode === 'periodic_motion';
    row.querySelectorAll('.rule-cam').forEach((el) => {
      const cam = el.dataset.cam;
      const isMotion = !!(RULES_STATE.motion[cam] && RULES_STATE.motion[cam].motion);
      const blink = rule.enabled && motionMode && isMotion;
      el.classList.toggle('blinking', blink);
    });
  });
}

function refreshRulesCountdowns() {
  for (const [ruleId, cd] of Object.entries(RULES_STATE.countdowns)) {
    applyCountdownToDom(ruleId, cd);
  }
}

function applyCountdownToDom(ruleId, cd) {
  const el = document.getElementById(`rule-cd-${ruleId}`);
  if (!el || el.hidden) return;
  const valueEl = el.querySelector('.rule-cd-value');
  if (!valueEl) return;
  if (cd.waiting_for_motion) {
    valueEl.textContent = 'waiting for motion';
    el.classList.add('paused');
  } else if (cd.paused) {
    valueEl.textContent = `${cd.remaining_s}s · paused (no motion)`;
    el.classList.add('paused');
  } else {
    valueEl.textContent = `${cd.remaining_s}s`;
    el.classList.remove('paused');
  }
}

function applySustainedToDom(ruleId, s) {
  const el = document.getElementById(`rule-su-${ruleId}`);
  if (!el) return;
  el.hidden = false;
  const valueEl = el.querySelector('.rule-su-value');
  const labelEl = el.querySelector('.rule-su-label');
  if (!valueEl || !labelEl) return;
  if (s.sustained) {
    labelEl.textContent = 'Sustained ✓';
    valueEl.textContent = `${s.elapsed_s}s ≥ ${s.min_duration_s}s`;
    el.classList.remove('candidate');
    el.classList.add('sustained');
  } else {
    labelEl.textContent = 'Detected';
    valueEl.textContent = `sustaining ${s.elapsed_s}s / ${s.min_duration_s}s · ${s.remaining_s}s left`;
    el.classList.remove('sustained');
    el.classList.add('candidate');
  }
}

function clearSustainedFromDom(ruleId) {
  const el = document.getElementById(`rule-su-${ruleId}`);
  if (!el) return;
  el.hidden = true;
  el.classList.remove('candidate', 'sustained');
}

// -------------------------------------------------------------
// Motion WS — push-based motion state for blinking camera badges
// -------------------------------------------------------------
function ensureRulesMotionWs() {
  if (RULES_STATE.motionWs && RULES_STATE.motionWs.readyState <= WebSocket.OPEN) return;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  let ws;
  try { ws = new WebSocket(`${proto}//${location.host}/api/frigate/motion/ws`); }
  catch { scheduleRulesMotionReconnect(); return; }
  RULES_STATE.motionWs = ws;
  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.type === 'snapshot') {
      RULES_STATE.motion = msg.cameras || {};
    } else if (msg.type === 'motion') {
      RULES_STATE.motion[msg.camera] = {
        motion: !!msg.motion,
        objects: msg.objects || [],
        audio_dbfs: msg.audio_dbfs ?? null,
        audio_labels: msg.audio_labels || [],
      };
    } else {
      return;
    }
    refreshRulesMotion();
    refreshRulesAudioMeters();
  };
  ws.onclose = () => { RULES_STATE.motionWs = null; scheduleRulesMotionReconnect(); };
  ws.onerror = () => { try { ws.close(); } catch {} };
}

function scheduleRulesMotionReconnect() {
  if (!document.getElementById('rules-list')) return;  // page left
  clearTimeout(RULES_STATE.motionReconnect);
  RULES_STATE.motionReconnect = setTimeout(ensureRulesMotionWs, 3000);
}

function closeRulesMotionWs() {
  clearTimeout(RULES_STATE.motionReconnect);
  RULES_STATE.motionReconnect = null;
  if (RULES_STATE.motionWs) {
    try { RULES_STATE.motionWs.close(); } catch {}
    RULES_STATE.motionWs = null;
  }
  RULES_STATE.motion = {};
  RULES_STATE.countdowns = {};
}

function renderRuleRow(rule) {
  const isExpanded = RULES_STATE.expanded.has(rule.id);
  const cams = rule.cameras || [];
  const mode = (rule.scan && rule.scan.mode) || 'periodic';
  const camBadges = cams.length
    ? cams.map((c) => `<span class="rule-badge rule-cam" data-cam="${escapeHtml(c)}" data-rule-id="${escapeHtml(rule.id)}">${escapeHtml(c)}</span>`).join('')
    : `<span class="rule-badge muted">no cameras</span>`;
  const showCountdown = rule.enabled && (mode === 'periodic' || mode === 'periodic_motion');
  const enabled = !!rule.enabled;
  return `
    <div class="rule-row ${enabled ? 'on' : 'off'}" data-rule-id="${escapeHtml(rule.id)}" data-scan-mode="${escapeHtml(mode)}">
      <div class="rule-row-head">
        <button class="rule-power" data-toggle-id="${escapeHtml(rule.id)}" aria-pressed="${enabled}" title="${enabled ? 'Turn rule off' : 'Turn rule on'}">
          <span class="rule-power-icon">⏻</span>
          <span class="rule-power-label">${enabled ? 'ON' : 'OFF'}</span>
        </button>
        <div class="rule-info">
          <div class="rule-name">${escapeHtml(rule.name || rule.id)}</div>
          <div class="rule-sub">
            ${camBadges}
            <span class="rule-badge">${escapeHtml(scanSummary(rule.scan))}</span>
            <span class="rule-badge muted" title="Vision model">${escapeHtml(modelSummary(rule.model))}</span>
            ${rule.fire_alarm ? '<span class="rule-badge red">🚨 alarm</span>' : ''}
            ${rule.store_iterations ? '<span class="rule-badge muted">store iterations</span>' : ''}
          </div>
          <div class="rule-countdown" id="rule-cd-${escapeHtml(rule.id)}" ${showCountdown ? '' : 'hidden'}>
            <span class="rule-cd-label">Next scan</span>
            <span class="rule-cd-value">—</span>
          </div>
          <div class="rule-sustained" id="rule-su-${escapeHtml(rule.id)}" hidden>
            <span class="rule-su-dot"></span>
            <span class="rule-su-label">Detected</span>
            <span class="rule-su-value">—</span>
          </div>
        </div>
        <div class="rule-stats">
          <div class="rule-count" title="Total triggers since rule was created">
            <div class="rule-count-num rule-count-trig" data-rule-id="${escapeHtml(rule.id)}">${rule.trigger_count || 0}</div>
            <div class="rule-count-lbl">total triggered</div>
          </div>
          <div class="rule-count" title="Total iterations since rule was created">
            <div class="rule-count-num rule-count-iter" data-rule-id="${escapeHtml(rule.id)}">${rule.iteration_count || 0}</div>
            <div class="rule-count-lbl">total iterations</div>
          </div>
        </div>
        <div class="rule-actions">
          <button class="btn secondary" data-rule-action="edit" data-rule-id="${escapeHtml(rule.id)}">Edit</button>
          <button class="btn secondary danger" data-rule-action="delete" data-rule-id="${escapeHtml(rule.id)}">Delete</button>
        </div>
        <button class="rule-expand" data-rule-action="expand" data-rule-id="${escapeHtml(rule.id)}"
                aria-expanded="${isExpanded}" aria-label="${isExpanded ? 'Hide details' : 'Show details'}"
                title="${isExpanded ? 'Hide details' : 'Show details'}">
          <svg class="rule-expand-arrow" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
            <polyline points="5,4 11,8 5,12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
      </div>
      ${cams.length ? `
        <div class="rule-audio-row" data-rule-id="${escapeHtml(rule.id)}">
          ${cams.map((c) => `
            <div class="rule-audio-cell">
              <span class="rule-audio-cam">${escapeHtml(c)}</span>
              <div class="audio-meter" data-cam-row="${escapeHtml(c)}" data-rule-id="${escapeHtml(rule.id)}" title="Audio level (dBFS)">
                <div class="audio-meter-bar"></div>
                <span class="audio-meter-val">—</span>
              </div>
            </div>
          `).join('')}
        </div>
      ` : ''}
      ${isExpanded ? `<div class="rule-row-detail" id="rule-detail-${escapeHtml(rule.id)}"><p class="hint">Loading history…</p></div>` : ''}
    </div>
  `;
}

function refreshRulesAudioMeters() {
  document.querySelectorAll('.rule-audio-row .audio-meter[data-cam-row]').forEach((meter) => {
    const cam = meter.dataset.camRow;
    const info = RULES_STATE.motion[cam] || { audio_dbfs: null, audio_labels: [] };
    applyAudioMeter(meter, info);
  });
}

function modelSummary(selector) {
  const s = (selector || '').trim();
  if (!s) return 'Gemini · auto';
  if (s.startsWith('ollama:')) return `Ollama · ${s.slice('ollama:'.length)}`;
  if (s.startsWith('gemini:')) {
    const m = s.slice('gemini:'.length);
    return m ? `Gemini · ${m}` : 'Gemini · auto';
  }
  return s;
}

function scanSummary(scan) {
  if (!scan) return 'no scan';
  const m = scan.mode || 'periodic';
  if (m === 'periodic') return `every ${scan.period_s || 60}s`;
  if (m === 'periodic_motion') return `motion + every ${scan.period_s || 60}s`;
  if (m === 'motion') return 'on motion';
  if (m === 'entity_state') return `on ${scan.entity_id || '?'} = ${scan.target_state || '?'}`;
  return m;
}

function onRuleAction(e) {
  const btn = e.currentTarget;
  const id = btn.dataset.ruleId;
  const action = btn.dataset.ruleAction;
  const rule = RULES_STATE.rules.find((r) => r.id === id);
  if (!rule) return;
  if (action === 'expand') toggleExpanded(rule);
  else if (action === 'edit') openRuleEditor(rule);
  else if (action === 'delete') confirmDeleteRule(rule);
  else if (action === 'clear-history') clearHistory(rule);
}

async function toggleExpanded(rule) {
  if (RULES_STATE.expanded.has(rule.id)) {
    RULES_STATE.expanded.delete(rule.id);
    renderRulesList();
    return;
  }
  RULES_STATE.expanded.add(rule.id);
  RULES_STATE.pagination[rule.id] = {
    triggers: { offset: 0, total: 0, items: [] },
    iterations: { offset: 0, total: 0, items: [] },
    tab: 'triggers',
  };
  renderRulesList();
  await mountHistoryShell(rule);
  await loadHistoryPage(rule, 'triggers');
}

async function mountHistoryShell(rule) {
  const detail = document.getElementById(`rule-detail-${rule.id}`);
  if (!detail) return;
  detail.innerHTML = `
    <div class="rule-history-tabs">
      <button class="tab active" data-tab="triggers" data-rule-action="tab" data-rule-id="${escapeHtml(rule.id)}">Triggers</button>
      ${rule.store_iterations ? `<button class="tab" data-tab="iterations" data-rule-action="tab" data-rule-id="${escapeHtml(rule.id)}">All iterations</button>` : ''}
      <span style="flex:1"></span>
      <button class="btn secondary" data-rule-action="clear-history" data-rule-id="${escapeHtml(rule.id)}">Clear history</button>
    </div>
    <div id="rule-history-${escapeHtml(rule.id)}"><p class="hint">Loading…</p></div>
  `;
  detail.querySelectorAll('[data-rule-action="tab"]').forEach((b) => b.addEventListener('click', onHistoryTab));
  detail.querySelector('[data-rule-action="clear-history"]').addEventListener('click', () => clearHistory(rule));
}

function renderHistoryFromCache(rule) {
  // Used after a re-render: rebuild the detail panel from cached pagination.
  mountHistoryShell(rule).then(() => {
    const pag = RULES_STATE.pagination[rule.id];
    if (!pag) return;
    const tab = pag.tab || 'triggers';
    const detail = document.getElementById(`rule-detail-${rule.id}`);
    detail?.querySelectorAll('[data-tab]').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
    if ((pag[tab].items || []).length === 0) {
      loadHistoryPage(rule, tab);
    } else {
      renderHistory(rule, tab);
    }
  });
}

async function onHistoryTab(e) {
  const btn = e.currentTarget;
  const id = btn.dataset.ruleId;
  const tab = btn.dataset.tab;
  const rule = RULES_STATE.rules.find((r) => r.id === id);
  if (!rule) return;
  const detail = document.getElementById(`rule-detail-${id}`);
  detail.querySelectorAll('[data-tab]').forEach((b) => b.classList.toggle('active', b === btn));
  RULES_STATE.pagination[rule.id].tab = tab;
  RULES_STATE.pagination[rule.id][tab] = { offset: 0, total: 0, items: [] };
  await loadHistoryPage(rule, tab);
}

async function loadHistoryPage(rule, kind) {
  const wrap = document.getElementById(`rule-history-${rule.id}`);
  if (!wrap) return;
  const pag = RULES_STATE.pagination[rule.id][kind];
  try {
    const r = await fetch(`/api/ai-camera/rules/${encodeURIComponent(rule.id)}/${kind}?offset=${pag.offset}&limit=20`);
    if (!r.ok) throw new Error(`http ${r.status}`);
    const data = await r.json();
    pag.total = data.total;
    pag.items.push(...(data.items || []));
    pag.offset = pag.items.length;
    renderHistory(rule, kind);
  } catch (e) {
    wrap.innerHTML = `<p class="hint" style="color:var(--err)">Failed to load ${kind}: ${escapeHtml(e.message)}</p>`;
  }
}

function renderHistory(rule, kind) {
  const wrap = document.getElementById(`rule-history-${rule.id}`);
  if (!wrap) return;
  const pag = RULES_STATE.pagination[rule.id][kind];
  if (!pag.items.length) {
    wrap.innerHTML = `<p class="hint">No ${kind} yet.</p>`;
    return;
  }
  const rows = pag.items.map((it) => historyEntryHtml(rule, it)).join('');
  const remaining = Math.max(0, pag.total - pag.items.length);
  const more = remaining > 0
    ? `<button class="btn secondary" id="history-more-${rule.id}-${kind}">Load 20 more (${remaining} remaining)</button>`
    : `<p class="hint" style="text-align:center">All ${pag.total} entries loaded.</p>`;
  wrap.innerHTML = `<div class="history-list">${rows}</div><div style="margin-top:10px;text-align:center">${more}</div>`;
  const btn = document.getElementById(`history-more-${rule.id}-${kind}`);
  if (btn) btn.addEventListener('click', () => loadHistoryPage(rule, kind));
}

function historyEntryHtml(rule, it) {
  // Episode-shaped trigger (sustained run): multiple iterations rolled into one row.
  if (Array.isArray(it.sequence) && it.sequence.length) {
    return episodeEntryHtml(rule, it);
  }

  const ts = it.ts ? new Date(it.ts * 1000).toLocaleString() : '';
  const cams = it.snap_cams && it.snap_cams.length ? it.snap_cams : (it.cameras || []);
  const reason = it.verdict_reason || (it.parsed && it.parsed.reason) || '';
  const triggered = !!it.triggered;
  const cls = triggered ? 'triggered' : 'not-triggered';
  const bbox = isValidBbox(it.bbox) ? it.bbox : (it.parsed && isValidBbox(it.parsed.bbox) ? it.parsed.bbox : null);
  const thumbs = cams.map((c) => renderThumbsForCamera(rule, it.iteration_id, c, bbox)).join('');
  return `
    <div class="history-entry ${cls}">
      <div class="history-meta">
        <strong>#${it.iteration_id}</strong>
        <span class="rule-badge ${triggered ? 'red' : 'muted'}">${triggered ? 'TRIGGERED' : 'no match'}</span>
        <span class="hint">${escapeHtml(it.trigger_reason || '')}</span>
        <span class="hint" style="margin-left:auto">${ts}</span>
      </div>
      ${reason ? `<div class="history-reason">${escapeHtml(reason)}</div>` : ''}
      ${thumbs ? `<div class="history-thumbs">${thumbs}</div>` : ''}
    </div>
  `;
}

function episodeEntryHtml(rule, ep) {
  const tsStart = ep.started_ts ? new Date(ep.started_ts * 1000).toLocaleTimeString() : '';
  const tsLast  = ep.last_ts    ? new Date(ep.last_ts * 1000).toLocaleTimeString()
                 : (ep.fired_ts ? new Date(ep.fired_ts * 1000).toLocaleTimeString() : tsStart);
  const reason  = ep.verdict_reason || '';
  const count   = ep.sequence.length;
  const durMs   = (ep.last_ts || ep.fired_ts || ep.started_ts || 0) - (ep.started_ts || 0);
  const durTxt  = durMs > 0 ? ` · ${Math.round(durMs)}s` : '';

  const iterRows = ep.sequence.map((seqIt) => {
    const cams = seqIt.snap_cams && seqIt.snap_cams.length ? seqIt.snap_cams : (seqIt.cameras || []);
    const bbox = isValidBbox(seqIt.bbox) ? seqIt.bbox : null;
    const thumbs = cams.map((c) => renderThumbsForCamera(rule, seqIt.iteration_id, c, bbox)).join('');
    const tsIt = seqIt.ts ? new Date(seqIt.ts * 1000).toLocaleTimeString() : '';
    return `
      <div class="ep-iter">
        <div class="ep-iter-meta">
          <strong>#${seqIt.iteration_id}</strong>
          <span class="hint">${escapeHtml(tsIt)}</span>
          ${seqIt.verdict_reason ? `<span class="hint">— ${escapeHtml(seqIt.verdict_reason)}</span>` : ''}
        </div>
        ${thumbs ? `<div class="history-thumbs">${thumbs}</div>` : ''}
      </div>
    `;
  }).join('');

  return `
    <div class="history-entry triggered episode" data-episode-id="${escapeHtml(ep.episode_id || '')}">
      <div class="history-meta">
        <strong>#${ep.iteration_id ?? ep.sequence[ep.sequence.length - 1].iteration_id}</strong>
        <span class="rule-badge red">TRIGGERED · ${count} frame${count === 1 ? '' : 's'}${durTxt}</span>
        <span class="hint">${escapeHtml(ep.trigger_reason || '')}</span>
        <span class="hint" style="margin-left:auto">${escapeHtml(tsStart)} → ${escapeHtml(tsLast)}</span>
      </div>
      ${reason ? `<div class="history-reason">${escapeHtml(reason)}</div>` : ''}
      <details class="ep-collapse">
        <summary>
          <span class="ep-count">${count}</span>
          <span class="ep-count-lbl">frame${count === 1 ? '' : 's'} captured during this trigger</span>
          <span class="ep-toggle">show / hide</span>
        </summary>
        <div class="ep-iter-list">${iterRows}</div>
      </details>
    </div>
  `;
}

function isValidBbox(b) {
  if (!b || typeof b !== 'object') return false;
  const { x0, y0, x1, y1 } = b;
  return Number.isFinite(x0) && Number.isFinite(y0)
      && Number.isFinite(x1) && Number.isFinite(y1)
      && x1 > x0 && y1 > y0;
}

function renderThumbsForCamera(rule, iterId, camera, bbox) {
  const src = `/api/ai-camera/rules/${encodeURIComponent(rule.id)}/snap/${iterId}/${encodeURIComponent(camera)}`;
  const plainAttrs = `
    class="history-thumb" loading="lazy"
    data-rule-id="${escapeHtml(rule.id)}"
    data-iter-id="${iterId}"
    data-camera="${escapeHtml(camera)}"
    src="${src}"
    alt="${escapeHtml(camera)}"
    title="Click to enlarge"
    onerror="this.replaceWith(Object.assign(document.createElement('div'),{textContent:'No snapshot',className:'preview-fallback'}))"`;
  const plain = `<div class="history-thumb-wrap"><img ${plainAttrs} /></div>`;

  if (!bbox || (bbox.camera && bbox.camera !== camera)) {
    return plain;
  }
  // Render annotated companion right next to the plain one. (Label text is
  // intentionally not drawn on the thumbnail — the meta row above the
  // thumbnails already states the verdict reason, and labels would either
  // be unreadable at 120px or comically large.)
  const w = bbox.x1 - bbox.x0;
  const h = bbox.y1 - bbox.y0;
  const annotated = `
    <div class="history-thumb-wrap annotated">
      <img ${plainAttrs} data-annotated="1" title="Annotated · click to enlarge" />
      <svg class="bbox-overlay" viewBox="0 0 1000 1000" preserveAspectRatio="none">
        <rect x="${bbox.x0}" y="${bbox.y0}" width="${w}" height="${h}" />
      </svg>
    </div>
  `;
  return `<div class="thumb-pair">${plain}${annotated}</div>`;
}

function findIterationInCache(ruleId, iterId) {
  const pag = RULES_STATE.pagination[ruleId];
  if (!pag) return null;
  const want = Number(iterId);
  for (const kind of ['triggers', 'iterations']) {
    const bucket = pag[kind];
    if (!bucket || !bucket.items) continue;
    for (const x of bucket.items) {
      if (Number(x.iteration_id) === want) return x;
      // Episode-shaped trigger: look inside the sequence and synthesise a
      // single-iteration view so the existing modal renderer still works.
      if (Array.isArray(x.sequence)) {
        const seqIt = x.sequence.find((s) => Number(s.iteration_id) === want);
        if (seqIt) {
          return {
            ...x,
            iteration_id: seqIt.iteration_id,
            ts: seqIt.ts,
            cameras: seqIt.cameras,
            snap_cams: seqIt.snap_cams,
            bbox: seqIt.bbox,
            verdict_reason: seqIt.verdict_reason || x.verdict_reason,
            triggered: true,
          };
        }
      }
    }
  }
  return null;
}

function openRuleSnapshotModal(ruleId, iterId, camera) {
  const rule = RULES_STATE.rules.find((r) => r.id === ruleId);
  const it = findIterationInCache(ruleId, iterId);
  if (!rule || !it) return;
  const ts = it.ts ? new Date(it.ts * 1000).toLocaleString() : '';
  const triggered = !!it.triggered;
  const reason = it.verdict_reason || (it.parsed && it.parsed.reason) || '(no reason returned)';
  const responseText = (it.response_text || '').trim();
  const triggerSrc = it.trigger_reason || '';
  const otherCams = (it.snap_cams && it.snap_cams.length ? it.snap_cams : (it.cameras || []))
    .filter((c) => c !== camera);
  const otherThumbs = otherCams.map((c) => `
    <img class="history-thumb" loading="lazy"
         data-rule-id="${escapeHtml(ruleId)}"
         data-iter-id="${it.iteration_id}"
         data-camera="${escapeHtml(c)}"
         src="/api/ai-camera/rules/${encodeURIComponent(ruleId)}/snap/${it.iteration_id}/${encodeURIComponent(c)}"
         alt="${escapeHtml(c)}"
         title="Switch view" />
  `).join('');
  // Bounding-box overlay (if the model returned one for THIS camera).
  const bbox = isValidBbox(it.bbox) && (!it.bbox.camera || it.bbox.camera === camera) ? it.bbox : null;
  const bboxOverlay = bbox ? `
    <svg class="bbox-overlay" viewBox="0 0 1000 1000" preserveAspectRatio="none">
      <rect x="${bbox.x0}" y="${bbox.y0}" width="${bbox.x1 - bbox.x0}" height="${bbox.y1 - bbox.y0}" />
    </svg>` : '';

  const bodyHtml = `
    <div class="snap-modal">
      <div class="live-frame bbox-frame">
        <img src="/api/ai-camera/rules/${encodeURIComponent(ruleId)}/snap/${it.iteration_id}/${encodeURIComponent(camera)}"
             alt="${escapeHtml(camera)}" />
        ${bboxOverlay}
      </div>
      ${otherThumbs ? `<div class="snap-modal-others"><span class="hint">Other cameras this iteration:</span><div class="history-thumbs">${otherThumbs}</div></div>` : ''}
      <dl class="snap-modal-meta">
        <dt>When</dt><dd>${escapeHtml(ts)}</dd>
        <dt>Rule</dt><dd>${escapeHtml(rule.name || rule.id)}</dd>
        <dt>Camera</dt><dd>${escapeHtml(camera)}</dd>
        <dt>Verdict</dt><dd>
          <span class="rule-badge ${triggered ? 'red' : 'muted'}">${triggered ? 'TRIGGERED' : 'no match'}</span>
        </dd>
        <dt>AI reason</dt><dd>${escapeHtml(reason)}</dd>
        <dt>Scheduled by</dt><dd>${escapeHtml(triggerSrc)}</dd>
        ${it.provider || it.model ? `<dt>Model</dt><dd>${escapeHtml(it.provider || '')}${it.provider && it.model ? ' · ' : ''}${escapeHtml(it.model || '')}</dd>` : ''}
        ${responseText ? `<dt>Raw response</dt><dd><pre class="snap-modal-raw">${escapeHtml(responseText)}</pre></dd>` : ''}
      </dl>
    </div>
  `;
  showModal({
    title: `Iteration #${it.iteration_id}`,
    sub: `${rule.name || rule.id} · ${camera}`,
    bodyHtml,
  });
  // Allow swapping to a sibling camera within the open modal.
  document.querySelectorAll('.snap-modal-others .history-thumb').forEach((img) => {
    img.addEventListener('click', () => openRuleSnapshotModal(ruleId, iterId, img.dataset.camera));
  });
}

function onRulesListClick(e) {
  const thumb = e.target.closest('.history-thumb');
  if (!thumb) return;
  const ruleId = thumb.dataset.ruleId;
  const iterId = thumb.dataset.iterId;
  const camera = thumb.dataset.camera;
  if (!ruleId || !iterId || !camera) return;
  openRuleSnapshotModal(ruleId, iterId, camera);
}

async function clearHistory(rule) {
  if (!confirm(`Clear all triggers and iterations for "${rule.name || rule.id}"?`)) return;
  try {
    const r = await fetch(`/api/ai-camera/rules/${encodeURIComponent(rule.id)}/history`, { method: 'DELETE' });
    if (!r.ok) throw new Error(`http ${r.status}`);
    await loadRules();
    const wasExpanded = RULES_STATE.expanded.has(rule.id);
    renderRulesList();
    if (wasExpanded) {
      const fresh = RULES_STATE.rules.find((x) => x.id === rule.id);
      RULES_STATE.pagination[rule.id] = {
        triggers: { offset: 0, total: 0, items: [] },
        iterations: { offset: 0, total: 0, items: [] },
        tab: 'triggers',
      };
      await mountHistoryShell(fresh);
      await loadHistoryPage(fresh, 'triggers');
    }
  } catch (e) {
    alert(`Clear failed: ${e.message}`);
  }
}

async function onTogglePower(e) {
  const btn = e.currentTarget;
  const id = btn.dataset.toggleId;
  const wasPressed = btn.getAttribute('aria-pressed') === 'true';
  const enabled = !wasPressed;
  btn.disabled = true;
  try {
    const r = await fetch(`/api/ai-camera/rules/${encodeURIComponent(id)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
    if (!r.ok) throw new Error(`http ${r.status}`);
    await loadRules();
    renderRulesList();
  } catch (err) {
    alert(`Toggle failed: ${err.message}`);
    btn.disabled = false;
  }
}

async function confirmDeleteRule(rule) {
  if (!confirm(`Delete rule "${rule.name || rule.id}" and all its history?`)) return;
  try {
    const r = await fetch(`/api/ai-camera/rules/${encodeURIComponent(rule.id)}`, { method: 'DELETE' });
    if (!r.ok) throw new Error(`http ${r.status}`);
    RULES_STATE.expanded.delete(rule.id);
    delete RULES_STATE.pagination[rule.id];
    await loadRules();
    renderRulesList();
  } catch (err) {
    alert(`Delete failed: ${err.message}`);
  }
}

function handleRulesEvent(msg) {
  if (!msg) return;
  if (!document.getElementById('rules-list')) return;  // not mounted
  if (msg.type === 'countdown') {
    RULES_STATE.countdowns[msg.rule_id] = {
      remaining_s: msg.remaining_s,
      total_s: msg.total_s,
      paused: !!msg.paused,
      waiting_for_motion: !!msg.waiting_for_motion,
    };
    applyCountdownToDom(msg.rule_id, RULES_STATE.countdowns[msg.rule_id]);
    return;
  }
  if (msg.type === 'sustained_progress') {
    applySustainedToDom(msg.rule_id, {
      elapsed_s: msg.elapsed_s,
      remaining_s: msg.remaining_s,
      min_duration_s: msg.min_duration_s,
      sustained: !!msg.sustained,
    });
    return;
  }
  if (msg.type === 'sustained_reset') {
    clearSustainedFromDom(msg.rule_id);
    return;
  }
  if (msg.type === 'trigger') {
    const rule = RULES_STATE.rules.find((r) => r.id === msg.rule_id);
    if (rule) {
      rule.trigger_count = (rule.trigger_count || 0) + 1;
      bumpCountInDom('rule-count-trig', msg.rule_id, rule.trigger_count);
      if (RULES_STATE.expanded.has(rule.id)) {
        RULES_STATE.pagination[rule.id].triggers = { offset: 0, total: 0, items: [] };
        loadHistoryPage(rule, 'triggers');
      }
      // The sustained-state chip stays visible (now "Sustained ✓") for a
      // moment then clears so the operator sees the cause of the trigger.
      setTimeout(() => clearSustainedFromDom(msg.rule_id), 6000);
    }
  } else if (msg.type === 'trigger_update' || msg.type === 'trigger_complete') {
    // The episode row on disk has been rewritten — refresh the triggers
    // page in place so the operator sees the new thumbnail(s) appear.
    const rule = RULES_STATE.rules.find((r) => r.id === msg.rule_id);
    if (rule && RULES_STATE.expanded.has(rule.id)) {
      const pag = RULES_STATE.pagination[rule.id];
      if (pag && (pag.tab || 'triggers') === 'triggers') {
        pag.triggers = { offset: 0, total: 0, items: [] };
        loadHistoryPage(rule, 'triggers');
      }
    }
  } else if (msg.type === 'iteration') {
    const rule = RULES_STATE.rules.find((r) => r.id === msg.rule_id);
    if (rule) {
      // Prefer the server-pushed count (authoritative) when present.
      rule.iteration_count = msg.iteration_count != null
        ? msg.iteration_count
        : (rule.iteration_count || 0) + 1;
      bumpCountInDom('rule-count-iter', msg.rule_id, rule.iteration_count);
      const pag = RULES_STATE.pagination[msg.rule_id];
      if (RULES_STATE.expanded.has(msg.rule_id) && rule.store_iterations && pag && pag.tab === 'iterations') {
        pag.iterations = { offset: 0, total: 0, items: [] };
        loadHistoryPage(rule, 'iterations');
      }
    }
  } else if (msg.type === 'rule_deleted' || msg.type === 'rule_updated') {
    loadRules().then(renderRulesList);
  }
}

function bumpCountInDom(cls, ruleId, value) {
  const el = document.querySelector(`.${cls}[data-rule-id="${CSS.escape(ruleId)}"]`);
  if (!el) return;
  el.textContent = value;
  el.classList.remove('pulse');
  void el.offsetWidth;  // restart the CSS animation
  el.classList.add('pulse');
}

// -------------------------------------------------------------
// Rule editor (shared modal — create + edit)
// -------------------------------------------------------------
function openRuleEditor(existing) {
  const seed = existing || {
    name: '', enabled: true, cameras: [], rule: '',
    scan: { mode: 'periodic_motion', period_s: 60 },
    action: null, cooldown_s: 60, fire_alarm: false, store_iterations: false,
    model: '',
  };
  const cams = RULES_STATE.cameras;
  const ents = RULES_STATE.haEntities;
  const camsHtml = cams.length
    ? cams.map((c) => `
      <label class="checkbox-row">
        <input type="checkbox" name="re-cam" value="${escapeHtml(c.name)}" ${(seed.cameras || []).includes(c.name) ? 'checked' : ''} />
        <span>${escapeHtml(c.name)}</span>
      </label>`).join('')
    : `<p class="hint">No Frigate cameras available.</p>`;
  const action = seed.action || {};
  const sd = action.service_data ? JSON.stringify(action.service_data) : '';
  const scan = seed.scan || { mode: 'periodic', period_s: 60 };

  const body = `
    <div class="rule-editor">
      <label class="field"><span class="lbl">Name</span>
        <input id="re-name" type="text" value="${escapeHtml(seed.name || '')}" placeholder="e.g. Person without hi-vis" />
      </label>
      <label class="field"><span class="lbl">Cameras</span>
        <div class="checkbox-list" id="re-cams">${camsHtml}</div>
      </label>
      <label class="field"><span class="lbl">Rule / trigger</span>
        <textarea id="re-rule" rows="3" placeholder="e.g. Trigger if a person is on site not wearing a hi-vis vest.">${escapeHtml(seed.rule || '')}</textarea>
      </label>
      <label class="field"><span class="lbl">Vision model</span>
        <select id="re-model"><option value="${escapeHtml(seed.model || '')}">Loading…</option></select>
        <span class="hint" style="margin-top:6px;display:block">Gemini runs in the cloud; Ollama runs locally on your GPU. Configure Ollama in <a href="#/settings">Settings</a> to see local models here.</span>
      </label>
      <label class="field"><span class="lbl">Scan pattern</span>
        <select id="re-scan-mode">
          <option value="periodic"${scan.mode === 'periodic' ? ' selected' : ''}>Periodic</option>
          <option value="motion"${scan.mode === 'motion' ? ' selected' : ''}>On motion (Frigate)</option>
          <option value="periodic_motion"${scan.mode === 'periodic_motion' ? ' selected' : ''}>Periodic + motion</option>
          <option value="entity_state"${scan.mode === 'entity_state' ? ' selected' : ''}>On HA entity state</option>
        </select>
      </label>
      <div id="re-scan-extra"></div>
      <details class="wake-words">
        <summary>Action when triggered (optional)</summary>
        <label class="field"><span class="lbl">Target entity</span>
          <input id="re-action-entity" type="text" value="${escapeHtml(action.entity_id || '')}" placeholder="light.alarm, switch.siren, …" list="re-entities-dl" />
          <datalist id="re-entities-dl">${ents.map((e) => `<option value="${escapeHtml(e.entity_id)}">${escapeHtml(e.friendly_name)}</option>`).join('')}</datalist>
        </label>
        <div class="row-2">
          <label class="field" style="margin:0"><span class="lbl">Service</span>
            <input id="re-action-service" type="text" value="${escapeHtml(action.service || 'turn_on')}" placeholder="turn_on" />
          </label>
          <label class="field" style="margin:0"><span class="lbl">Cooldown (s)</span>
            <input id="re-cooldown" type="number" min="0" value="${seed.cooldown_s ?? 60}" />
          </label>
        </div>
        <label class="field"><span class="lbl">Service data (JSON, optional)</span>
          <textarea id="re-action-data" rows="2" placeholder='{"brightness_pct": 100}'>${escapeHtml(sd)}</textarea>
        </label>
      </details>
      <label class="field">
        <span class="lbl">Sustained duration (seconds)</span>
        <input id="re-min-duration" type="number" min="0" value="${seed.min_duration_s ?? 0}" />
        <span class="hint" style="margin-top:6px;display:block">The action fires only when the model has said <em>triggered</em> continuously for this long. <code>0</code> = fire on first hit (default). Example: <code>30</code> for "alert if the door is open for more than 30 seconds". While a candidate is waiting to be confirmed, the scan rate auto-bumps to ~5 s.</span>
      </label>
      <div class="rule-flags">
        <label class="checkbox-row">
          <input id="re-fire-alarm" type="checkbox" ${seed.fire_alarm ? 'checked' : ''} />
          <span><strong>Fire system-wide alarm</strong> on trigger (red banner + siren, dismissible)</span>
        </label>
        <label class="checkbox-row">
          <input id="re-store-iter" type="checkbox" ${seed.store_iterations ? 'checked' : ''} />
          <span>Store every iteration (not just triggers). Triggers are always stored.</span>
        </label>
        <label class="checkbox-row">
          <input id="re-enabled" type="checkbox" ${seed.enabled ? 'checked' : ''} />
          <span>Enabled — start scanning immediately</span>
        </label>
      </div>
      <div id="re-error" class="hint" style="color:var(--err);min-height:1.2em"></div>
      <div class="btn-row" style="margin-top:10px">
        <button class="btn" id="re-save">${existing ? 'Save changes' : 'Create rule'}</button>
        <button class="btn secondary" id="re-cancel">Cancel</button>
      </div>
    </div>
  `;
  showModal({
    title: existing ? 'Edit rule' : 'New rule',
    sub: existing ? existing.id : '',
    bodyHtml: body,
  });
  renderRuleEditorScanExtra(scan);
  document.getElementById('re-scan-mode').addEventListener('change', (e) => {
    renderRuleEditorScanExtra({ mode: e.target.value, period_s: getEditorPeriod() || 60 });
  });
  document.getElementById('re-save').addEventListener('click', () => saveRuleFromEditor(existing));
  document.getElementById('re-cancel').addEventListener('click', closeModal);
  // Populate the model dropdown (async, best-effort).
  AiCameraRules.listModels().then(({ options }) => {
    const sel = document.getElementById('re-model');
    if (!sel) return;
    const current = seed.model || '';
    const knownIds = new Set(options.map((o) => o.id));
    sel.innerHTML = options.map((o) => `
      <option value="${escapeHtml(o.id)}" ${o.id === current ? 'selected' : ''}>${escapeHtml(o.label)}</option>
    `).join('');
    // If the rule was saved with a model that isn't currently available
    // (e.g. user removed Ollama, or pulled a different tag), keep it as
    // a disabled option so the user sees what's saved.
    if (current && !knownIds.has(current)) {
      const opt = document.createElement('option');
      opt.value = current;
      opt.textContent = `${current} (unavailable)`;
      opt.selected = true;
      sel.appendChild(opt);
    }
  }).catch(() => { /* leave the loading option */ });
}

function getEditorPeriod() {
  const el = document.getElementById('re-period');
  return el ? parseInt(el.value, 10) : null;
}

function renderRuleEditorScanExtra(scan) {
  const wrap = document.getElementById('re-scan-extra');
  if (!wrap) return;
  const mode = scan.mode || 'periodic';
  if (mode === 'periodic' || mode === 'periodic_motion') {
    wrap.innerHTML = `
      <label class="field"><span class="lbl">Scan period (1–300 seconds)</span>
        <input id="re-period" type="number" min="1" max="300" value="${scan.period_s || 60}" />
        <span class="hint">1s for critical alerts (eats Gemini quota fast); 60–300s for normal monitoring.</span>
      </label>`;
  } else if (mode === 'entity_state') {
    wrap.innerHTML = `
      <div class="row-2">
        <label class="field" style="margin:0"><span class="lbl">HA entity</span>
          <input id="re-ent-id" type="text" value="${escapeHtml(scan.entity_id || '')}" list="re-entities-dl" placeholder="binary_sensor.door" />
        </label>
        <label class="field" style="margin:0"><span class="lbl">Target state</span>
          <input id="re-target-state" type="text" value="${escapeHtml(scan.target_state || 'on')}" placeholder="on" />
        </label>
      </div>`;
  } else {
    wrap.innerHTML = '';
  }
}

async function saveRuleFromEditor(existing) {
  const errEl = document.getElementById('re-error');
  errEl.textContent = '';
  const name = document.getElementById('re-name').value.trim();
  const ruleText = document.getElementById('re-rule').value.trim();
  const cameras = [...document.querySelectorAll('input[name="re-cam"]:checked')].map((c) => c.value);
  const mode = document.getElementById('re-scan-mode').value;
  const scan = { mode };
  if (mode === 'periodic' || mode === 'periodic_motion') {
    const v = parseInt(document.getElementById('re-period').value, 10);
    scan.period_s = Math.max(1, Math.min(300, isNaN(v) ? 60 : v));
  } else if (mode === 'entity_state') {
    scan.entity_id = document.getElementById('re-ent-id').value.trim();
    scan.target_state = document.getElementById('re-target-state').value.trim();
  }
  const entity_id = document.getElementById('re-action-entity').value.trim();
  let action = null;
  if (entity_id) {
    const service = document.getElementById('re-action-service').value.trim() || 'turn_on';
    const domain = entity_id.split('.')[0] || 'homeassistant';
    let service_data = null;
    const sdText = document.getElementById('re-action-data').value.trim();
    if (sdText) {
      try { service_data = JSON.parse(sdText); }
      catch (e) { errEl.textContent = `Service data JSON: ${e.message}`; return; }
    }
    action = { domain, service, entity_id, service_data };
  }
  const cooldown_s = parseInt(document.getElementById('re-cooldown').value, 10) || 0;
  const min_duration_s = Math.max(0, parseInt(document.getElementById('re-min-duration').value, 10) || 0);
  const fire_alarm = document.getElementById('re-fire-alarm').checked;
  const store_iterations = document.getElementById('re-store-iter').checked;
  const enabled = document.getElementById('re-enabled').checked;

  if (!name) { errEl.textContent = 'Name is required.'; return; }
  if (!ruleText) { errEl.textContent = 'Rule text is required.'; return; }
  if (cameras.length === 0) { errEl.textContent = 'Pick at least one camera.'; return; }
  if (mode === 'entity_state' && (!scan.entity_id || !scan.target_state)) {
    errEl.textContent = 'Entity-state scan needs an entity and a target state.'; return;
  }

  const model = (document.getElementById('re-model')?.value || '').trim();
  const payload = { name, rule: ruleText, cameras, scan, action, cooldown_s, min_duration_s, fire_alarm, store_iterations, enabled, model };
  try {
    const url = existing && existing.id
      ? `/api/ai-camera/rules/${encodeURIComponent(existing.id)}`
      : '/api/ai-camera/rules';
    const method = existing && existing.id ? 'PATCH' : 'POST';
    const r = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    if (!r.ok) {
      const txt = await r.text().catch(() => '');
      throw new Error(`http ${r.status}: ${txt.slice(0, 200)}`);
    }
    closeModal();
    await loadRules();
    renderRulesList();
  } catch (e) {
    errEl.textContent = `Save failed: ${e.message}`;
  }
}

// -------------------------------------------------------------
// AI-Camera · Playground — vision rule runner
// -------------------------------------------------------------
const AI_PG = {
  ws: null,
  active: false,
  iterations: [],     // {iteration_id, trigger_reason, timestamp, cameras, snapshots, parsed, triggered, response_text, action_status?}
  byId: new Map(),    // iteration_id -> object above
  cameras: [],        // available frigate cameras
  haEntities: [],     // {entity_id, friendly_name, ...}

  // Live previews
  previewCameras: [],
  previewSnapTimer: null,
  motionWs: null,            // push-based motion updates via MQTT bridge
  motionState: {},           // {camera: {motion: bool, objects: [..]}}
  motionReconnect: null,

};

async function renderAiCameraPlayground(root) {
  // Preflight: need Frigate + Gemini key. HA is optional (only required for actions / entity_state scan).
  let frigateCfg, liveCfg;
  try {
    [frigateCfg, liveCfg] = await Promise.all([
      Frigate.getConfig(),
      LiveAgent.getConfig(),
    ]);
  } catch (e) {
    root.innerHTML = `<div class="empty-state"><h3>Backend error</h3><p>${escapeHtml(e.message)}</p></div>`;
    return;
  }
  if (!frigateCfg.url || !liveCfg.api_key_set) {
    root.innerHTML = `
      <div class="page-header">
        <h1>AI-Camera · Playground</h1>
      </div>
      <div class="empty-state">
        <h3>Configure prerequisites</h3>
        <p>This page needs <strong>Frigate</strong> (camera frames) and a <strong>Gemini API key</strong> (vision analysis).${
          !frigateCfg.url ? ' Frigate URL is missing.' : ''
        }${!liveCfg.api_key_set ? ' Gemini API key is missing.' : ''} Configure them in <a href="#/settings">Settings</a>.</p>
      </div>
    `;
    return;
  }

  root.innerHTML = `
    <div class="page-header">
      <h1>AI-Camera · Playground</h1>
      <p>Build a vision rule: pick camera(s), describe what to look for, choose when to scan, and what action to fire. Each session opens its own Gemini Live session — independent from the Smart Home Live Agent.</p>
    </div>

    <div class="split">
      <!-- LEFT: configuration -->
      <div class="card" style="margin:0">
        <h2>Configuration</h2>

        <label class="field">
          <span class="lbl">Cameras (one or more)</span>
          <div id="pg-cameras" class="checkbox-list"><p class="hint">Loading…</p></div>
        </label>

        <label class="field">
          <span class="lbl">Rule / trigger</span>
          <textarea id="pg-rule" rows="3" placeholder="e.g. Trigger if you see a person on site not wearing a hi-vis vest."></textarea>
        </label>

        <label class="field">
          <span class="lbl">Vision model</span>
          <select id="pg-model"><option value="">Loading…</option></select>
          <span class="hint" style="margin-top:6px;display:block">Gemini runs in the cloud; Ollama runs locally on your GPU. Configure Ollama in <a href="#/settings">Settings</a> to see local models here.</span>
        </label>

        <label class="field">
          <span class="lbl">Scan pattern</span>
          <select id="pg-scan-mode">
            <option value="periodic">Periodic</option>
            <option value="motion">On motion (Frigate)</option>
            <option value="periodic_motion">Periodic + motion</option>
            <option value="entity_state">On HA entity state</option>
          </select>
        </label>

        <div id="pg-scan-extra" class="scan-extra"></div>

        <details class="wake-words" id="pg-action-section">
          <summary>Action when triggered (optional)</summary>
          <div style="margin-top:8px">
            <label class="field">
              <span class="lbl">Target entity</span>
              <input type="text" id="pg-action-entity" placeholder="light.alarm, switch.siren, …" list="pg-entities-datalist" />
              <datalist id="pg-entities-datalist"></datalist>
            </label>
            <label class="field">
              <span class="lbl">Service</span>
              <input type="text" id="pg-action-service" placeholder="turn_on" value="turn_on" />
              <span class="hint" style="margin-top:6px;display:block">Domain comes from the entity id. The service must be valid for that domain (e.g. <code>turn_on</code>, <code>turn_off</code>, <code>open_cover</code>).</span>
            </label>
            <label class="field">
              <span class="lbl">Service data (JSON, optional)</span>
              <textarea id="pg-action-data" rows="2" placeholder='{"brightness_pct": 100}'></textarea>
            </label>
            <label class="field">
              <span class="lbl">Cooldown (seconds)</span>
              <input type="number" id="pg-action-cooldown" min="0" value="60" />
            </label>
          </div>
        </details>

        <div class="btn-row" style="margin-top:10px">
          <button class="btn" id="pg-start">Start Session</button>
          <button class="btn secondary" id="pg-stop" disabled>Stop Session</button>
        </div>

        <div class="status-pill" style="margin-top:10px">
          <span class="status-dot" id="pg-dot"></span>
          <span class="status-label">Session:</span>
          <span class="status-text" id="pg-status">Idle</span>
        </div>

        <div class="status-pill" id="pg-countdown" hidden style="margin-top:8px">
          <span class="status-dot" id="pg-countdown-dot"></span>
          <span class="status-label">Next scan:</span>
          <span class="status-text" id="pg-countdown-text">—</span>
        </div>
      </div>

      <!-- RIGHT: logs + results -->
      <div style="display:flex;flex-direction:column;gap:14px">
        <div class="card" style="margin:0">
          <div class="events-meta">
            <h2 style="margin:0">Live previews</h2>
            <span class="count" id="pg-preview-count">0</span>
          </div>
          <div id="pg-previews"><p class="hint">Tick a camera on the left to add a live preview here.</p></div>
        </div>

        <div class="card" style="margin:0">
          <div class="events-meta">
            <h2 style="margin:0">Triggered results</h2>
            <span class="count" id="pg-results-count">0</span>
          </div>
          <div id="pg-results" class="pg-results"><p class="hint">No triggered iterations yet.</p></div>
        </div>

        <div class="card" style="margin:0">
          <div class="events-meta">
            <h2 style="margin:0">Iteration log</h2>
            <span class="count" id="pg-log-count">0</span>
          </div>
          <div id="pg-log" class="pg-log"><p class="hint">Logs will appear here once the session starts.</p></div>
        </div>
      </div>
    </div>
  `;

  // Reset state when the page mounts.
  AI_PG.iterations = [];
  AI_PG.byId = new Map();
  refreshLogUI();
  refreshResultsUI();

  // Load cameras (best-effort).
  Frigate.getCameras().then((cams) => {
    AI_PG.cameras = cams;
    const wrap = document.getElementById('pg-cameras');
    if (!wrap) return;
    if (cams.length === 0) {
      wrap.innerHTML = `<p class="hint">No cameras returned by Frigate.</p>`;
      return;
    }
    wrap.innerHTML = cams.map((c) => `
      <label class="checkbox-row">
        <input type="checkbox" value="${escapeHtml(c.name)}" />
        <span>${escapeHtml(c.name)}</span>
      </label>
    `).join('');
    // React to each tick/untick: previews follow the selection.
    wrap.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
      cb.addEventListener('change', updatePlaygroundPreviews);
    });
  }).catch((e) => {
    document.getElementById('pg-cameras').innerHTML = `<p class="hint" style="color:var(--err)">Cameras failed: ${escapeHtml(e.message)}</p>`;
  });

  // Load HA entities for datalist + entity-state scan picker. Best-effort.
  HA.getEntities().then((ents) => {
    AI_PG.haEntities = ents;
    const dl = document.getElementById('pg-entities-datalist');
    if (dl) dl.innerHTML = ents.map((e) => `<option value="${escapeHtml(e.entity_id)}">${escapeHtml(e.friendly_name)}</option>`).join('');
    refreshScanExtra();
  }).catch(() => {});

  // Populate the model dropdown (best-effort — the page still works on Gemini default if this fails).
  AiCameraRules.listModels().then(({ options }) => {
    const sel = document.getElementById('pg-model');
    if (!sel || !options) return;
    sel.innerHTML = options.map((o) => `
      <option value="${escapeHtml(o.id)}">${escapeHtml(o.label)}</option>
    `).join('');
  }).catch(() => { /* leave the loading option */ });

  document.getElementById('pg-scan-mode').addEventListener('change', refreshScanExtra);
  refreshScanExtra();

  document.getElementById('pg-start').addEventListener('click', startPlayground);
  document.getElementById('pg-stop').addEventListener('click', stopPlayground);

  // Delegated thumbnail click → open large in the existing modal.
  ['pg-log', 'pg-results'].forEach((id) => {
    const container = document.getElementById(id);
    container?.addEventListener('click', (e) => {
      const fig = e.target.closest('.iter-thumb');
      if (!fig || !container.contains(fig)) return;
      const iterId = parseInt(fig.dataset.iterId, 10);
      const cam = fig.dataset.camera;
      const it = AI_PG.byId.get(iterId);
      if (!it || !cam) return;
      openSnapshotModal(it, cam);
    });
  });
}

function openSnapshotModal(it, camera) {
  const b64 = it.snapshots && it.snapshots[camera];
  if (!b64) return;
  const ts = it.timestamp ? new Date(it.timestamp * 1000).toLocaleString() : '';
  const triggered = it.triggered === true ? ' · TRIGGERED' : it.triggered === false ? ' · no match' : '';
  showModal({
    title: camera,
    sub: `Iteration #${it.iteration_id}${triggered} · ${escapeHtml(it.trigger_reason || '')} · ${ts}`,
    openUrl: null,
    bodyHtml: `
      <div class="live-frame">
        <img src="data:image/jpeg;base64,${b64}" alt="${escapeHtml(camera)}" />
      </div>
    `,
  });
}

// -------------------------------------------------------------
// Playground live previews
// -------------------------------------------------------------
function updatePlaygroundPreviews() {
  const selected = [...document.querySelectorAll('#pg-cameras input[type="checkbox"]:checked')].map((c) => c.value);
  AI_PG.previewCameras = selected;
  renderPreviewTiles();
  refreshPreviewSnapshots();   // immediate
  // Reflect any motion state we've already received for these cameras.
  selected.forEach(updateMotionBadge);
  restartPreviewTimers();
  // Open the push-based motion WS lazily, once at least one tile is showing.
  if (selected.length > 0) ensureMotionWs();
  else closeMotionWs();
}

function renderPreviewTiles() {
  const wrap = document.getElementById('pg-previews');
  const cnt  = document.getElementById('pg-preview-count');
  if (!wrap || !cnt) return;
  cnt.textContent = AI_PG.previewCameras.length;
  if (AI_PG.previewCameras.length === 0) {
    wrap.innerHTML = `<p class="hint">Tick a camera on the left to add a live preview here.</p>`;
    return;
  }
  wrap.innerHTML = `
    <div class="preview-grid">
      ${AI_PG.previewCameras.map((cam) => `
        <div class="preview-tile" data-camera="${escapeHtml(cam)}">
          <div class="preview-thumb">
            <img class="preview-img" data-src="/api/frigate/snapshot/${encodeURIComponent(cam)}" alt="${escapeHtml(cam)}"
              onerror="this.replaceWith(Object.assign(document.createElement('div'),{textContent:'No snapshot',className:'preview-fallback'}))" />
            <div class="preview-badges">
              <span class="motion-badge" data-motion-for="${escapeHtml(cam)}">—</span>
            </div>
          </div>
          <div class="preview-name">${escapeHtml(cam)}</div>
        </div>
      `).join('')}
    </div>
  `;
}

function refreshPreviewSnapshots() {
  if (AI_PG.previewCameras.length === 0) return;
  const cb = Date.now();
  document.querySelectorAll('.preview-img').forEach((img) => {
    const src = img.dataset.src;
    if (src) img.src = `${src}?h=360&cb=${cb}`;
  });
}

function updateMotionBadge(camera) {
  const badge = document.querySelector(`[data-motion-for="${cssEsc(camera)}"]`);
  if (!badge) return;
  const info = AI_PG.motionState[camera] || { motion: false, objects: [] };
  if (info.motion) {
    const labels = (info.objects || []).join(', ');
    badge.textContent = labels ? `● MOTION · ${labels}` : '● MOTION';
    badge.classList.add('active');
  } else {
    badge.textContent = '○ idle';
    badge.classList.remove('active');
  }
}

function ensureMotionWs() {
  if (AI_PG.motionWs && AI_PG.motionWs.readyState <= WebSocket.OPEN) return;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/api/frigate/motion/ws`);
  AI_PG.motionWs = ws;
  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.type === 'snapshot') {
      AI_PG.motionState = msg.cameras || {};
      AI_PG.previewCameras.forEach(updateMotionBadge);
    } else if (msg.type === 'motion') {
      AI_PG.motionState[msg.camera] = { motion: !!msg.motion, objects: msg.objects || [] };
      updateMotionBadge(msg.camera);
    }
  };
  ws.onclose = () => {
    AI_PG.motionWs = null;
    // Reconnect if previews are still on screen.
    if (AI_PG.previewCameras.length > 0) {
      clearTimeout(AI_PG.motionReconnect);
      AI_PG.motionReconnect = setTimeout(ensureMotionWs, 3000);
    }
  };
  ws.onerror = () => { /* onclose will handle reconnect */ };
}

function closeMotionWs() {
  clearTimeout(AI_PG.motionReconnect);
  AI_PG.motionReconnect = null;
  if (AI_PG.motionWs) {
    try { AI_PG.motionWs.close(); } catch {}
    AI_PG.motionWs = null;
  }
}

function restartPreviewTimers() {
  stopPreviewTimers();
  if (AI_PG.previewCameras.length === 0) return;
  AI_PG.previewSnapTimer = setInterval(refreshPreviewSnapshots, 1500);
}

function stopPreviewTimers() {
  if (AI_PG.previewSnapTimer) clearInterval(AI_PG.previewSnapTimer);
  AI_PG.previewSnapTimer = null;
}

function refreshScanExtra() {
  const extra = document.getElementById('pg-scan-extra');
  if (!extra) return;
  const mode = document.getElementById('pg-scan-mode').value;
  if (mode === 'periodic' || mode === 'periodic_motion') {
    extra.innerHTML = `
      <label class="field">
        <span class="lbl">Period (seconds)</span>
        <input type="number" id="pg-period" min="2" value="30" />
      </label>
    `;
  } else if (mode === 'entity_state') {
    const opts = (AI_PG.haEntities || []).map((e) => `<option value="${escapeHtml(e.entity_id)}">${escapeHtml(e.entity_id)} — ${escapeHtml(e.friendly_name)}</option>`).join('');
    extra.innerHTML = `
      <label class="field">
        <span class="lbl">Watch entity</span>
        <input type="text" id="pg-watch-entity" placeholder="binary_sensor.front_door_motion" list="pg-entities-datalist" />
      </label>
      <label class="field">
        <span class="lbl">When state equals</span>
        <input type="text" id="pg-watch-state" placeholder="on" value="on" />
      </label>
    `;
  } else {
    extra.innerHTML = '';
  }
}

function setPgStatus(status, text) {
  const dot = document.getElementById('pg-dot');
  const txt = document.getElementById('pg-status');
  if (dot) {
    dot.classList.remove('ok', 'err', 'warn', 'checking');
    if (status !== 'idle') dot.classList.add(status);
  }
  if (txt) txt.textContent = text;
}

function collectPlaygroundConfig() {
  const cameras = [...document.querySelectorAll('#pg-cameras input[type=checkbox]:checked')].map((c) => c.value);
  const rule = (document.getElementById('pg-rule').value || '').trim();
  const mode = document.getElementById('pg-scan-mode').value;
  const scan = { mode };
  if (mode === 'periodic' || mode === 'periodic_motion') {
    scan.period_s = parseInt(document.getElementById('pg-period').value, 10) || 30;
  }
  if (mode === 'entity_state') {
    scan.entity_id    = (document.getElementById('pg-watch-entity').value || '').trim();
    scan.target_state = (document.getElementById('pg-watch-state').value || '').trim();
  }

  let action = null;
  const entity = (document.getElementById('pg-action-entity').value || '').trim();
  if (entity) {
    const domain = entity.split('.')[0];
    const service = (document.getElementById('pg-action-service').value || 'turn_on').trim();
    const rawData = (document.getElementById('pg-action-data').value || '').trim();
    let serviceData = null;
    if (rawData) {
      try { serviceData = JSON.parse(rawData); }
      catch { throw new Error('Action service data must be valid JSON.'); }
    }
    action = { domain, service, entity_id: entity, service_data: serviceData };
  }
  const cooldown_s = parseInt(document.getElementById('pg-action-cooldown').value, 10) || 0;
  const model = (document.getElementById('pg-model')?.value || '').trim();
  return { cameras, rule, scan, action, cooldown_s, model };
}

async function startPlayground() {
  let cfg;
  try { cfg = collectPlaygroundConfig(); }
  catch (e) { alert(e.message); return; }
  if (cfg.cameras.length === 0) { alert('Pick at least one camera.'); return; }
  if (!cfg.rule)                 { alert('Describe the rule to evaluate.'); return; }

  // Create the AudioContext inside the user-gesture so the browser won't
  // block the alarm tone when it fires later.
  primeAlarmAudio();

  setPgStatus('checking', 'Connecting…');
  AI_PG.iterations = [];
  AI_PG.byId = new Map();
  refreshLogUI(); refreshResultsUI();

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${proto}//${location.host}/api/ai-camera/playground/ws`;
  const ws = new WebSocket(url);
  AI_PG.ws = ws;
  AI_PG.active = true;

  ws.onopen = () => {
    ws.send(JSON.stringify({ type: 'start', ...cfg }));
  };
  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    handlePgMessage(msg);
  };
  ws.onerror = () => setPgStatus('err', 'WebSocket error');
  ws.onclose = (ev) => {
    AI_PG.active = false;
    AI_PG.ws = null;
    document.getElementById('pg-start').disabled = false;
    document.getElementById('pg-stop').disabled = true;
    const cd = document.getElementById('pg-countdown');
    if (cd) cd.hidden = true;
    if (ev.wasClean) setPgStatus('idle', 'Stopped');
    else setPgStatus('err', `Closed (${ev.code})`);
  };

  document.getElementById('pg-start').disabled = true;
  document.getElementById('pg-stop').disabled = false;
}

function stopPlayground() {
  if (AI_PG.ws && AI_PG.ws.readyState === WebSocket.OPEN) {
    try { AI_PG.ws.send(JSON.stringify({ type: 'stop' })); } catch {}
    try { AI_PG.ws.close(); } catch {}
  }
  AI_PG.active = false;
}

function handlePgMessage(msg) {
  switch (msg.type) {
    case 'ready':
      setPgStatus('ok', `Live · ${msg.model}`);
      break;
    case 'iteration_start': {
      const iter = {
        iteration_id: msg.iteration_id,
        trigger_reason: msg.trigger_reason,
        timestamp: msg.timestamp,
        cameras: msg.cameras,
        snapshots: msg.snapshots,
        triggered: null,    // pending
        response_text: null,
        parsed: null,
        action_status: null,
      };
      AI_PG.iterations.unshift(iter);
      AI_PG.byId.set(iter.iteration_id, iter);
      refreshLogUI();
      break;
    }
    case 'iteration_result': {
      const it = AI_PG.byId.get(msg.iteration_id);
      if (it) {
        it.triggered = !!msg.triggered;
        it.response_text = msg.response_text || '';
        it.parsed = msg.parsed || null;
        it.finished_at = msg.finished_at;
      }
      refreshLogUI(); refreshResultsUI();
      if (msg.triggered) {
        const reason = (msg.parsed && msg.parsed.reason) || (msg.response_text || '').slice(0, 200);
        fireAlarm(reason);
      }
      break;
    }
    case 'iteration_skipped':
    case 'iteration_error': {
      const id = msg.iteration_id ?? null;
      const it = id !== null ? AI_PG.byId.get(id) : null;
      if (it) {
        it.triggered = false;
        it.response_text = msg.error || msg.message || '';
        it.parsed = { error: true, message: it.response_text };
      } else {
        AI_PG.iterations.unshift({
          iteration_id: id ?? Date.now(),
          trigger_reason: '—',
          timestamp: Date.now() / 1000,
          cameras: [], snapshots: {},
          triggered: false, response_text: msg.error || msg.message || '',
          parsed: { error: true },
        });
      }
      refreshLogUI();
      break;
    }
    case 'action_executed': {
      const it = AI_PG.byId.get(msg.iteration_id);
      if (it) { it.action_status = { ok: true, action: msg.action, result: msg.result }; }
      refreshLogUI(); refreshResultsUI();
      break;
    }
    case 'action_cooldown': {
      const it = AI_PG.byId.get(msg.iteration_id);
      if (it) { it.action_status = { skipped: true, remaining_s: msg.remaining_s }; }
      refreshLogUI(); refreshResultsUI();
      break;
    }
    case 'action_error': {
      const it = AI_PG.byId.get(msg.iteration_id);
      if (it) { it.action_status = { ok: false, error: msg.error }; }
      refreshLogUI(); refreshResultsUI();
      break;
    }
    case 'countdown':
      updatePgCountdown(msg);
      break;
    case 'error':
      setPgStatus('err', msg.message || 'error');
      break;
  }
}

function updatePgCountdown(msg) {
  const pill = document.getElementById('pg-countdown');
  const dot  = document.getElementById('pg-countdown-dot');
  const text = document.getElementById('pg-countdown-text');
  if (!pill || !text || !dot) return;
  pill.hidden = false;

  dot.classList.remove('ok', 'err', 'warn', 'checking');
  if (msg.waiting_for_motion) {
    text.textContent = 'waiting for motion';
    dot.classList.add('warn');
  } else if (msg.paused) {
    text.textContent = `${msg.remaining_s}s · paused (no motion)`;
    dot.classList.add('warn');
  } else {
    text.textContent = `${msg.remaining_s}s`;
    dot.classList.add('checking'); // pulse during countdown
  }
}

function refreshLogUI() {
  const wrap = document.getElementById('pg-log');
  const cnt = document.getElementById('pg-log-count');
  if (!wrap || !cnt) return;
  cnt.textContent = AI_PG.iterations.length;
  if (AI_PG.iterations.length === 0) {
    wrap.innerHTML = `<p class="hint">Logs will appear here once the session starts.</p>`;
    return;
  }
  wrap.innerHTML = AI_PG.iterations.map(renderIterationCard).join('');
}

function refreshResultsUI() {
  const wrap = document.getElementById('pg-results');
  const cnt = document.getElementById('pg-results-count');
  if (!wrap || !cnt) return;
  const triggered = AI_PG.iterations.filter((it) => it.triggered === true);
  cnt.textContent = triggered.length;
  if (triggered.length === 0) {
    wrap.innerHTML = `<p class="hint">No triggered iterations yet.</p>`;
    return;
  }
  wrap.innerHTML = triggered.map((it) => renderIterationCard(it, { highlight: true })).join('');
}

// -------------------------------------------------------------
// Alarm — shell-level. Red strobe + looping two-tone siren until silenced.
// Primed on the first user gesture (anywhere) so the siren can play when
// a rule fires later without a per-page user click. Triggered both by the
// Playground (locally) and by the shell's events WS (any saved rule).
// -------------------------------------------------------------
const Alarm = {
  ctx: null,
  osc: null,
  timer: null,
  active: false,
  ws: null,
  reconnectTimer: null,
};

function primeAlarmAudio() {
  if (Alarm.ctx) return;
  try {
    Alarm.ctx = new (window.AudioContext || window.webkitAudioContext)();
  } catch { /* AudioContext not supported — alarm will be silent */ }
}

function startAlarmAudio() {
  const ctx = Alarm.ctx;
  if (!ctx || Alarm.timer) return;
  if (ctx.state === 'suspended') {
    try { ctx.resume(); } catch {}
  }
  const osc = ctx.createOscillator();
  osc.type = 'square';
  const gain = ctx.createGain();
  gain.gain.value = 0.08;
  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.start();
  Alarm.osc = osc;
  let high = true;
  const tick = () => {
    if (!Alarm.osc) return;
    Alarm.osc.frequency.setValueAtTime(high ? 1100 : 800, ctx.currentTime);
    high = !high;
  };
  tick();
  Alarm.timer = setInterval(tick, 500);
}

function stopAlarmAudio() {
  if (Alarm.timer) clearInterval(Alarm.timer);
  Alarm.timer = null;
  if (Alarm.osc) {
    try { Alarm.osc.stop(); } catch {}
    Alarm.osc = null;
  }
}

function fireAlarm(detail) {
  const message = detail || 'Rule triggered';
  let banner = document.getElementById('alarm-banner');
  if (!banner) {
    const strobe = document.createElement('div');
    strobe.id = 'alarm-strobe';
    strobe.className = 'alarm-strobe';
    document.body.appendChild(strobe);

    banner = document.createElement('div');
    banner.id = 'alarm-banner';
    banner.className = 'alarm-banner';
    banner.innerHTML = `
      <div class="alarm-banner-text">
        <strong>🚨 ALARM</strong>
        <span class="detail" id="alarm-banner-detail"></span>
      </div>
      <button class="btn btn-silent" id="alarm-silence-btn">Silence alarm</button>
    `;
    document.body.appendChild(banner);
    document.getElementById('alarm-silence-btn').addEventListener('click', silenceAlarm);
    Alarm.active = true;
    startAlarmAudio();
  }
  const detailEl = document.getElementById('alarm-banner-detail');
  if (detailEl) detailEl.textContent = message;
}

function silenceAlarm() {
  Alarm.active = false;
  document.getElementById('alarm-strobe')?.remove();
  document.getElementById('alarm-banner')?.remove();
  stopAlarmAudio();
}

function initAlarm() {
  const onFirstGesture = () => {
    primeAlarmAudio();
    document.removeEventListener('pointerdown', onFirstGesture);
    document.removeEventListener('keydown', onFirstGesture);
  };
  document.addEventListener('pointerdown', onFirstGesture, { once: true });
  document.addEventListener('keydown', onFirstGesture, { once: true });
  connectRulesEventWs();
}

function connectRulesEventWs() {
  if (Alarm.ws && Alarm.ws.readyState !== WebSocket.CLOSED) return;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${proto}//${location.host}/api/ai-camera/events/ws`;
  let ws;
  try { ws = new WebSocket(url); } catch { scheduleReconnect(); return; }
  Alarm.ws = ws;
  ws.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    if (msg.type === 'trigger' && msg.fire_alarm) {
      const detail = `${msg.rule_name || 'Rule'} — ${msg.verdict_reason || msg.trigger_reason || ''}`;
      fireAlarm(detail);
    }
    // Anything mounted on the Rules page listens here to refresh its data.
    window.dispatchEvent(new CustomEvent('ai-camera-event', { detail: msg }));
  };
  ws.onclose = () => { Alarm.ws = null; scheduleReconnect(); };
  ws.onerror = () => { try { ws.close(); } catch {} };
}

function scheduleReconnect() {
  clearTimeout(Alarm.reconnectTimer);
  Alarm.reconnectTimer = setTimeout(connectRulesEventWs, 3000);
}

function renderIterationCard(it, opts = {}) {
  const stateClass = it.triggered === true ? 'iter-card triggered'
    : it.triggered === false ? 'iter-card not-triggered'
    : 'iter-card pending';
  const stateLabel = it.triggered === true ? 'TRIGGERED'
    : it.triggered === false ? 'no match'
    : '…analyzing';
  const reason = it.parsed && it.parsed.reason ? it.parsed.reason : (it.response_text || '').slice(0, 240);
  const cams = it.snapshots ? Object.entries(it.snapshots) : [];
  const ts = it.timestamp ? new Date(it.timestamp * 1000).toLocaleTimeString() : '';

  let actionLine = '';
  if (it.action_status) {
    if (it.action_status.ok) actionLine = `<div class="iter-action ok">✓ Action fired: ${escapeHtml(it.action_status.action?.domain || '')}.${escapeHtml(it.action_status.action?.service || '')} on ${escapeHtml(it.action_status.action?.entity_id || '')}</div>`;
    else if (it.action_status.skipped) actionLine = `<div class="iter-action warn">⏸ Action skipped (cooldown ${Math.ceil(it.action_status.remaining_s || 0)}s)</div>`;
    else actionLine = `<div class="iter-action err">✗ Action failed: ${escapeHtml(it.action_status.error || '')}</div>`;
  }

  return `
    <div class="${stateClass}${opts.highlight ? ' highlight' : ''}">
      <div class="iter-head">
        <div>
          <span class="iter-state-pill ${it.triggered === true ? 'on' : it.triggered === false ? 'off' : ''}">${stateLabel}</span>
          <span class="iter-meta">#${it.iteration_id} · ${escapeHtml(it.trigger_reason || '')} · ${escapeHtml(ts)}</span>
        </div>
      </div>
      ${cams.length ? `
        <div class="iter-thumbs">
          ${cams.map(([cam, b64]) => `
            <figure class="iter-thumb" data-iter-id="${it.iteration_id}" data-camera="${escapeHtml(cam)}" title="Click to enlarge">
              <img src="data:image/jpeg;base64,${b64}" alt="${escapeHtml(cam)}" />
              <figcaption>${escapeHtml(cam)}</figcaption>
            </figure>
          `).join('')}
        </div>` : ''}
      ${reason ? `<div class="iter-reason">${escapeHtml(reason)}</div>` : ''}
      ${actionLine}
    </div>
  `;
}

// Expose for hashchange-based cleanup.
window.AiCameraSession = {
  isActive: () => AI_PG.active || AI_PG.previewCameras.length > 0,
  stop: () => {
    try { stopPlayground(); } catch {}
    try { stopPreviewTimers(); } catch {}
    try { closeMotionWs(); } catch {}
    AI_PG.previewCameras = [];
  },
};

// =============================================================
// AI-Camera · Test AI Model — one-shot vision Q&A
// History survives navigation within the SPA (lives on window).
// =============================================================
window.AI_TEST = window.AI_TEST || {
  history: [],       // [{id, timestamp, provider, model, prompt, response, error, imageDataUrl, latency_ms}]
  models: null,      // {gemini: [...], ollama: [...]} once loaded
  loadingModels: false,
};

async function renderAiCameraTestModel(root) {
  root.innerHTML = `
    <div class="page-header">
      <h1>AI-Camera · Test AI Model</h1>
      <p>Pick a model, upload an image, ask it anything. Every exchange is recorded in the History panel at the bottom. Configure providers in <a href="#/settings">Settings</a> (Gemini API key, Ollama URL).</p>
    </div>

    <div class="split">
      <div class="card" style="margin:0">
        <h2>Ask</h2>

        <label class="field">
          <span class="lbl">Model</span>
          <select id="tm-model" disabled>
            <option>Loading models…</option>
          </select>
          <span class="hint" style="margin-top:6px;display:block">Vision-capable models only. Gemini models come from your account's ListModels; Ollama models from your local instance.</span>
        </label>

        <label class="field">
          <span class="lbl">Image</span>
          <input type="file" id="tm-image" accept="image/*" />
        </label>

        <div id="tm-preview-wrap" hidden>
          <div class="live-frame" style="max-width:340px">
            <img id="tm-preview" alt="" />
          </div>
        </div>

        <label class="field">
          <span class="lbl">Prompt</span>
          <textarea id="tm-prompt" rows="4" placeholder="What can you see? Is there a person in this image? Describe the scene in two sentences."></textarea>
        </label>

        <div class="btn-row" style="margin-top:8px">
          <button class="btn" id="tm-ask">Ask AI</button>
          <button class="btn secondary" id="tm-clear-history">Clear history</button>
        </div>

        <div class="feedback" id="tm-feedback"></div>
      </div>

      <div class="card" style="margin:0">
        <h2>Latest response</h2>
        <div id="tm-latest"><p class="hint">No response yet.</p></div>
      </div>
    </div>

    <div class="card" style="margin-top:16px">
      <div class="events-meta">
        <h2 style="margin:0">History</h2>
        <span class="count" id="tm-history-count">${window.AI_TEST.history.length}</span>
      </div>
      <div id="tm-history"></div>
    </div>
  `;

  // Wire image preview.
  const imgInput = document.getElementById('tm-image');
  imgInput.addEventListener('change', () => {
    const f = imgInput.files?.[0];
    const wrap = document.getElementById('tm-preview-wrap');
    const img = document.getElementById('tm-preview');
    if (!f) { wrap.hidden = true; return; }
    const url = URL.createObjectURL(f);
    img.src = url;
    img.onload = () => URL.revokeObjectURL(url);
    wrap.hidden = false;
  });

  document.getElementById('tm-ask').addEventListener('click', testAskClick);
  document.getElementById('tm-clear-history').addEventListener('click', () => {
    window.AI_TEST.history = [];
    refreshTestHistory();
  });

  refreshTestHistory();

  // Load models (cache for the SPA lifetime; reload on demand).
  if (!window.AI_TEST.models && !window.AI_TEST.loadingModels) {
    await loadTestModels();
  } else if (window.AI_TEST.models) {
    populateTestModelDropdown();
  }
}

async function loadTestModels() {
  window.AI_TEST.loadingModels = true;
  try {
    const r = await fetch('/api/ai-camera/test/models');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    window.AI_TEST.models = await r.json();
    populateTestModelDropdown();
  } catch (e) {
    const sel = document.getElementById('tm-model');
    if (sel) sel.innerHTML = `<option value="">— failed to load: ${escapeHtml(e.message)} —</option>`;
  } finally {
    window.AI_TEST.loadingModels = false;
  }
}

function populateTestModelDropdown() {
  const sel = document.getElementById('tm-model');
  if (!sel) return;
  const data = window.AI_TEST.models || { gemini: [], ollama: [] };
  const groups = [];
  if (data.gemini && data.gemini.length) {
    groups.push(`<optgroup label="Gemini">${data.gemini.map((m) =>
      `<option value="gemini:${escapeHtml(m.name)}">${escapeHtml(m.display_name || m.name)}</option>`).join('')}</optgroup>`);
  }
  if (data.ollama && data.ollama.length) {
    groups.push(`<optgroup label="Ollama (local)">${data.ollama.map((m) =>
      `<option value="ollama:${escapeHtml(m.name)}">${escapeHtml(m.display_name || m.name)}</option>`).join('')}</optgroup>`);
  }
  if (!groups.length) {
    sel.innerHTML = `<option value="">— No models. Configure Gemini key and/or Ollama URL in Settings. —</option>`;
    sel.disabled = true;
    return;
  }
  sel.innerHTML = groups.join('');
  sel.disabled = false;
}

async function testAskClick() {
  const feedback = document.getElementById('tm-feedback');
  const btn = document.getElementById('tm-ask');
  const sel = document.getElementById('tm-model');
  const fileInput = document.getElementById('tm-image');
  const prompt = (document.getElementById('tm-prompt').value || '').trim();

  const selector = sel.value || '';
  const [provider, model] = selector.split(':', 2);
  const file = fileInput.files?.[0];

  if (!provider || !model) { showFeedback(feedback, 'err', 'Pick a model.'); return; }
  if (!file)              { showFeedback(feedback, 'err', 'Upload an image first.'); return; }
  if (!prompt)            { showFeedback(feedback, 'err', 'Type a prompt.'); return; }

  btn.disabled = true;
  showFeedback(feedback, 'ok', `Asking ${provider}:${model}…`);

  // Read the image into a data URL once for both display and history.
  const imageDataUrl = await new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(file);
  });

  const form = new FormData();
  form.append('provider', provider);
  form.append('model', model);
  form.append('prompt', prompt);
  form.append('image', file);

  let result;
  try {
    const res = await fetch('/api/ai-camera/test/ask', { method: 'POST', body: form });
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`HTTP ${res.status}${text ? ` — ${text.slice(0, 160)}` : ''}`);
    }
    result = await res.json();
  } catch (e) {
    result = { ok: false, provider, model, error: e.message };
  } finally {
    btn.disabled = false;
  }

  const entry = {
    id: Date.now(),
    timestamp: Date.now() / 1000,
    provider: result.provider || provider,
    model: result.model || model,
    prompt,
    response: result.ok ? (result.text || '') : '',
    error: result.ok ? null : (result.error || 'Failed'),
    imageDataUrl,
    latency_ms: result.latency_ms || null,
  };
  window.AI_TEST.history.unshift(entry);
  if (window.AI_TEST.history.length > 50) window.AI_TEST.history.length = 50;

  renderTestLatest(entry);
  refreshTestHistory();

  showFeedback(feedback, result.ok ? 'ok' : 'err',
    result.ok
      ? `Done in ${result.latency_ms ?? '?'} ms.`
      : `Failed: ${entry.error}`);
}

function renderTestLatest(entry) {
  const wrap = document.getElementById('tm-latest');
  if (!wrap) return;
  if (entry.error) {
    wrap.innerHTML = `
      <div class="domain-chip">${escapeHtml(entry.provider)} · ${escapeHtml(entry.model)}</div>
      <div class="iter-action err" style="margin-top:10px">${escapeHtml(entry.error)}</div>
    `;
    return;
  }
  wrap.innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap">
      <span class="domain-chip">${escapeHtml(entry.provider)}</span>
      <span class="entity-control-id">${escapeHtml(entry.model)}</span>
      ${entry.latency_ms ? `<span class="hint">· ${entry.latency_ms} ms</span>` : ''}
    </div>
    <div class="tm-response">${escapeHtml(entry.response || '(empty response)')}</div>
  `;
}

function refreshTestHistory() {
  const wrap = document.getElementById('tm-history');
  const cnt = document.getElementById('tm-history-count');
  if (!wrap || !cnt) return;
  cnt.textContent = window.AI_TEST.history.length;
  if (window.AI_TEST.history.length === 0) {
    wrap.innerHTML = `<p class="hint">No questions yet. Ask one above and it'll appear here.</p>`;
    return;
  }
  wrap.innerHTML = `
    <div class="tm-history-list">
      ${window.AI_TEST.history.map((e) => renderTestHistoryEntry(e)).join('')}
    </div>
  `;
  // Click any thumbnail → open in the modal.
  wrap.querySelectorAll('.tm-history-thumb').forEach((el) => {
    el.addEventListener('click', () => {
      const id = parseInt(el.dataset.id, 10);
      const entry = window.AI_TEST.history.find((x) => x.id === id);
      if (entry) openTestHistoryModal(entry);
    });
  });
}

function renderTestHistoryEntry(e) {
  const ts = e.timestamp ? new Date(e.timestamp * 1000).toLocaleString() : '';
  const statusCls = e.error ? 'err' : 'ok';
  return `
    <div class="tm-history-row ${statusCls}">
      <div class="tm-history-thumb" data-id="${e.id}" title="Click to enlarge">
        <img src="${escapeHtml(e.imageDataUrl || '')}" alt="" />
      </div>
      <div class="tm-history-body">
        <div class="tm-history-meta">
          <span class="domain-chip">${escapeHtml(e.provider)}</span>
          <span class="entity-control-id">${escapeHtml(e.model)}</span>
          <span class="hint">${escapeHtml(ts)}${e.latency_ms ? ` · ${e.latency_ms} ms` : ''}</span>
        </div>
        <div class="tm-history-prompt"><strong>Q:</strong> ${escapeHtml(e.prompt)}</div>
        ${e.error
          ? `<div class="iter-action err">${escapeHtml(e.error)}</div>`
          : `<div class="tm-history-response">${escapeHtml(e.response || '(empty)')}</div>`}
      </div>
    </div>
  `;
}

function openTestHistoryModal(entry) {
  showModal({
    title: `${entry.provider} · ${entry.model}`,
    sub: `${new Date(entry.timestamp * 1000).toLocaleString()}${entry.latency_ms ? ` · ${entry.latency_ms} ms` : ''}`,
    openUrl: null,
    bodyHtml: `
      <div class="live-frame" style="margin-bottom:14px">
        <img src="${escapeHtml(entry.imageDataUrl || '')}" alt="" />
      </div>
      <div style="padding:0 4px"><strong>Prompt:</strong></div>
      <div class="tm-response" style="margin:6px 0 12px">${escapeHtml(entry.prompt)}</div>
      <div style="padding:0 4px"><strong>${entry.error ? 'Error' : 'Response'}:</strong></div>
      <div class="tm-response" style="margin-top:6px${entry.error ? ';color:var(--err)' : ''}">${escapeHtml(entry.error || entry.response || '(empty)')}</div>
    `,
  });
}

// =============================================================
// SIP Phone — Extension page
// =============================================================
async function renderSipExtension(root) {
  let cfg;
  try { cfg = await Sip.getConfig(); }
  catch (e) {
    root.innerHTML = `<div class="empty-state"><h3>Backend error</h3><p>${escapeHtml(e.message)}</p></div>`;
    return;
  }

  if (!cfg.ws_url || !cfg.extension || !cfg.password_set) {
    root.innerHTML = `
      <div class="page-header">
        <h1>SIP Phone · Extension</h1>
      </div>
      <div class="empty-state">
        <h3>Configure SIP first</h3>
        <p>Add your PBX <strong>WebSocket URL</strong>, <strong>Extension</strong>, and <strong>Password</strong> in <a href="#/settings">Settings → SIP softphone</a>.</p>
        <p class="hint" style="margin-top:8px">Suggested PBX: Asterisk in Proxmox with <code>chan_pjsip</code>, <code>transport=wss</code>, an extension with a strong password, and TLS certificates so the browser will accept the <code>wss://</code> URL.</p>
      </div>
    `;
    return;
  }

  // Fetch the password by issuing an "echo" POST that doesn't change anything
  // — the GET intentionally hides the password, but the softphone needs it.
  // We instead require the user to type it in Settings, then the same POST
  // they made already persisted it; we read it back through a tiny dedicated
  // endpoint. Cleanest fix: re-fetch via a private endpoint. For now, ask the
  // user to re-enter the password if they cleared it — but normally we have
  // it cached server-side and will get it via /api/sip/config when we add a
  // secret-leak endpoint. To keep this self-contained, we read the password
  // out of the form state at session-start time by making a second POST that
  // returns it inside `password_set` only. Simpler approach: pass the
  // password back from the backend just for the SIP page. Add a dedicated
  // endpoint later if you want it more secure than that.

  root.innerHTML = `
    <div class="page-header">
      <h1>SIP Phone · Extension</h1>
      <p>Extension <strong>${escapeHtml(cfg.extension)}</strong> · <code>${escapeHtml(cfg.ws_url)}</code></p>
    </div>

    <div class="split">
      <!-- LEFT: phone (status, keypad, dial, active call) -->
      <div class="card" style="margin:0">
        <h2>Phone</h2>

        <div class="status-pill" id="phone-status" style="margin-bottom:12px">
          <span class="status-dot" id="phone-status-dot"></span>
          <span class="status-label">State:</span>
          <span class="status-text" id="phone-status-text">starting…</span>
        </div>

        <div class="btn-row" style="margin-bottom:10px">
          <button class="btn" id="btn-sip-register">Register</button>
          <button class="btn secondary" id="btn-sip-unregister" disabled>Unregister</button>
        </div>

        <label class="field">
          <span class="lbl">Dial</span>
          <div style="display:flex;gap:6px">
            <input type="text" id="sip-dial-input" placeholder="1002 or sip:user@host" />
            <button class="btn" id="btn-sip-dial" disabled>Call</button>
          </div>
        </label>

        <div class="keypad" id="sip-keypad" aria-label="Dial pad">
          ${['1','2','3','4','5','6','7','8','9','*','0','#'].map((d) =>
            `<button class="keypad-key" data-digit="${d}">${d}</button>`).join('')}
        </div>

        <div class="call-panel" id="call-panel" hidden>
          <div class="call-peer">
            <div class="call-peer-name" id="call-peer-name">—</div>
            <div class="call-peer-meta" id="call-peer-meta">idle</div>
          </div>
          <div class="call-timer" id="call-timer">00:00</div>
          <div class="btn-row">
            <button class="btn secondary" id="btn-call-mute">🎙 Mute</button>
            <button class="btn danger" id="btn-call-hangup">⏻ Hangup</button>
          </div>
        </div>
      </div>

      <!-- RIGHT: recent calls -->
      <div class="card" style="margin:0">
        <div class="events-meta">
          <h2 style="margin:0">Recent calls</h2>
          <span class="count" id="sip-history-count">0</span>
        </div>
        <div id="sip-history"><p class="hint">No calls yet.</p></div>
      </div>
    </div>

    <div class="modal-backdrop" id="sip-incoming-modal" hidden>
      <div class="modal" role="dialog" aria-modal="true">
        <header class="modal-header">
          <div>
            <div class="modal-title">📞 Incoming call</div>
            <div class="modal-sub" id="sip-incoming-peer">—</div>
          </div>
        </header>
        <div class="modal-body">
          <div class="btn-row" style="justify-content:center;gap:14px">
            <button class="btn" id="btn-sip-accept">Accept</button>
            <button class="btn danger" id="btn-sip-reject">Reject</button>
          </div>
        </div>
      </div>
    </div>
  `;

  // ----- Wire UI -----
  // Keypad: dual-purpose. Off-call → append to dial input. On-call → DTMF.
  document.querySelectorAll('#sip-keypad .keypad-key').forEach((btn) => {
    btn.addEventListener('click', () => {
      const d = btn.dataset.digit;
      if (window.SipPhone.callState() === 'in-call') {
        window.SipPhone.sendDtmf(d);
      } else {
        const input = document.getElementById('sip-dial-input');
        input.value = (input.value || '') + d;
      }
    });
  });

  document.getElementById('btn-sip-dial').addEventListener('click', () => {
    const target = (document.getElementById('sip-dial-input').value || '').trim();
    if (!target) return;
    const res = window.SipPhone.dial(target);
    if (!res.ok) alert(res.error);
  });

  document.getElementById('btn-sip-register').addEventListener('click', () => startSipSession(cfg));
  document.getElementById('btn-sip-unregister').addEventListener('click', () => window.SipPhone.stopPhone());
  document.getElementById('btn-call-hangup').addEventListener('click', () => window.SipPhone.hangup());
  document.getElementById('btn-call-mute').addEventListener('click', (e) => {
    const muted = e.currentTarget.classList.toggle('active');
    window.SipPhone.setMuted(muted);
    e.currentTarget.textContent = muted ? '🔇 Muted' : '🎙 Mute';
  });
  document.getElementById('btn-sip-accept').addEventListener('click', () => {
    document.getElementById('sip-incoming-modal').hidden = true;
    window.SipPhone.answer();
  });
  document.getElementById('btn-sip-reject').addEventListener('click', () => {
    document.getElementById('sip-incoming-modal').hidden = true;
    window.SipPhone.rejectIncoming();
  });

  // Subscribe to phone events for UI updates.
  let timerId = null;
  function refreshUI() {
    const state = window.SipPhone.callState();
    const statusText = document.getElementById('phone-status-text');
    const statusDot  = document.getElementById('phone-status-dot');
    if (!statusText || !statusDot) return;
    statusDot.classList.remove('ok','err','warn','checking');
    if (state === 'in-call')      { statusText.textContent = 'In call'; statusDot.classList.add('ok'); }
    else if (state === 'ringing') { statusText.textContent = 'Ringing — incoming'; statusDot.classList.add('warn'); }
    else if (state === 'idle')    { statusText.textContent = 'Registered · idle'; statusDot.classList.add('ok'); }
    else                          { statusText.textContent = 'Not registered'; statusDot.classList.add('err'); }

    const dialing = state === 'idle';
    document.getElementById('btn-sip-dial').disabled = !dialing;
    document.getElementById('btn-sip-register').disabled = state !== 'offline';
    document.getElementById('btn-sip-unregister').disabled = state === 'offline';

    const panel = document.getElementById('call-panel');
    if (state === 'in-call') panel.hidden = false;
    else                     panel.hidden = true;
  }

  window.SipPhone.subscribe((ev) => {
    switch (ev.type) {
      case 'starting': break;
      case 'transport':
        if (ev.state === 'connected') setSipHealth('checking', 'WS connected, registering…');
        break;
      case 'registered':
        setSipHealth('ok', `Registered · ${ev.extension}`);
        break;
      case 'unregistered':
        setSipHealth('warn', 'Unregistered');
        break;
      case 'register_failed':
        setSipHealth('err', `Register failed: ${ev.cause}`);
        break;
      case 'incoming':
        document.getElementById('sip-incoming-peer').textContent = ev.peer;
        document.getElementById('sip-incoming-modal').hidden = false;
        break;
      case 'incoming_cleared':
        document.getElementById('sip-incoming-modal').hidden = true;
        break;
      case 'session': {
        const peerName = document.getElementById('call-peer-name');
        const peerMeta = document.getElementById('call-peer-meta');
        if (peerName) peerName.textContent = ev.peer || '—';
        if (peerMeta) peerMeta.textContent = ev.state;
        if (ev.state === 'connected') {
          let secs = 0;
          if (timerId) clearInterval(timerId);
          const tEl = document.getElementById('call-timer');
          if (tEl) tEl.textContent = '00:00';
          timerId = setInterval(() => {
            secs += 1;
            if (tEl) tEl.textContent = `${String(Math.floor(secs / 60)).padStart(2,'0')}:${String(secs % 60).padStart(2,'0')}`;
          }, 1000);
        }
        if (ev.state === 'ended' || ev.state === 'failed') {
          if (timerId) { clearInterval(timerId); timerId = null; }
        }
        break;
      }
      case 'history':
        renderSipHistory();
        break;
      case 'fatal':
        setSipHealth('err', ev.message);
        break;
    }
    refreshUI();
  });

  renderSipHistory();
  refreshUI();

  // Auto-start: the phone tries to register as soon as the page mounts.
  await startSipSession(cfg);
}

async function startSipSession(cfgFromGet) {
  // Re-fetch via a tiny private channel so we have the actual password.
  // We use the same POST that the Settings card uses but with no fields —
  // the backend returns the *current* config minus the password. Since GET
  // hides the password, the page asks the user to keep it in Settings and
  // we pass nothing here. JsSIP needs the password client-side, so we now
  // need the backend to expose it for this page. Use the dedicated endpoint
  // (added below).
  let creds;
  try {
    const r = await fetch('/api/sip/credentials');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    creds = await r.json();
  } catch (e) {
    setSipHealth('err', `Could not read SIP credentials: ${e.message}`);
    return;
  }
  if (!creds.password) {
    setSipHealth('err', 'SIP password is not stored on the backend. Save it in Settings.');
    return;
  }
  window.SipPhone.startPhone(creds);
}

function renderSipHistory() {
  const wrap = document.getElementById('sip-history');
  const cnt  = document.getElementById('sip-history-count');
  if (!wrap || !cnt) return;
  const hist = window.SipPhone.getHistory();
  cnt.textContent = hist.length;
  if (hist.length === 0) {
    wrap.innerHTML = `<p class="hint">No calls yet.</p>`;
    return;
  }
  wrap.innerHTML = `
    <div class="sip-history-list">
      ${hist.map((h) => {
        const ts = new Date(h.ts * 1000).toLocaleString();
        const dur = `${String(Math.floor(h.duration_s / 60)).padStart(2,'0')}:${String(h.duration_s % 60).padStart(2,'0')}`;
        const arrow = h.direction === 'in' ? '↙' : '↗';
        const cls = h.status === 'completed' ? 'ok'
                  : h.status === 'missed'    ? 'warn'
                  :                            'err';
        return `
          <div class="sip-history-row ${cls}">
            <div class="sip-history-arrow">${arrow}</div>
            <div class="sip-history-main">
              <div class="sip-history-peer">${escapeHtml(h.peer)}</div>
              <div class="sip-history-meta">${escapeHtml(h.status)} · ${escapeHtml(dur)} · ${escapeHtml(ts)}</div>
            </div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

function renderNotFound(root) {
  root.innerHTML = `
    <div class="empty-state">
      <h3>Page not found</h3>
      <p><a href="#/home">Go home</a></p>
    </div>
  `;
}

// =============================================================
// Helpers
// =============================================================
function showFeedback(el, kind, msg) {
  el.className = `feedback show ${kind}`;
  el.textContent = msg;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function capitalize(s) {
  if (!s) return '';
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function formatTimestamp(unix) {
  if (!unix) return '—';
  return new Date(unix * 1000).toLocaleString();
}

function formatDuration(start, end) {
  if (!start) return '';
  if (!end) return 'ongoing';
  const secs = Math.max(0, Math.floor(end - start));
  if (secs < 60) return `${secs}s`;
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return s ? `${m}m ${s}s` : `${m}m`;
}

// <input type="datetime-local"> requires "YYYY-MM-DDTHH:MM" in local time.
function dtLocalString(d) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function dtLocalToUnix(v) {
  if (!v) return null;
  const t = new Date(v).getTime();
  return Number.isFinite(t) ? Math.floor(t / 1000) : null;
}

// =============================================================
// Theme + sidebar
// =============================================================
function applyTheme() {
  document.documentElement.dataset.theme = prefs.theme;
}

function toggleTheme() {
  prefs.theme = prefs.theme === 'dark' ? 'light' : 'dark';
  savePrefs();
  applyTheme();
}

function applySidebarState() {
  const sb = document.getElementById('sidebar');
  if (!sb) return;
  sb.classList.toggle('collapsed', !!prefs.sidebarCollapsed);
}

function toggleSidebar() {
  prefs.sidebarCollapsed = !prefs.sidebarCollapsed;
  savePrefs();
  applySidebarState();
}

function toggleMobileSidebar() {
  document.getElementById('sidebar')?.classList.toggle('open');
}

// =============================================================
// Init
// =============================================================
function initNav() {
  document.querySelectorAll('.nav-toggle').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const sb = document.getElementById('sidebar');
      // In collapsed desktop mode, expand the sidebar instead of opening a hidden submenu.
      if (sb?.classList.contains('collapsed')) {
        toggleSidebar();
        return;
      }
      btn.closest('.nav-group').classList.toggle('open');
    });
  });

  document.getElementById('theme-toggle')?.addEventListener('click', toggleTheme);
  document.getElementById('sidebar-toggle')?.addEventListener('click', toggleSidebar);
  document.getElementById('sidebar-toggle-mobile')?.addEventListener('click', toggleMobileSidebar);
}

function initModal() {
  const backdrop = document.getElementById('modal-backdrop');
  document.getElementById('modal-close')?.addEventListener('click', closeModal);
  backdrop?.addEventListener('click', (e) => {
    if (e.target === backdrop) closeModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && backdrop && !backdrop.hidden) closeModal();
  });
}

window.addEventListener('hashchange', navigate);
window.addEventListener('DOMContentLoaded', () => {
  applyTheme();
  applySidebarState();
  initNav();
  initModal();
  initAlarm();
  if (!location.hash) location.hash = '#/home';
  navigate();
  refreshHealth();
  startHealthPolling();
});
