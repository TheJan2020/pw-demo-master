# Remote Ollama via Tailscale

How to run Ollama on your **home Windows machine** (with the RTX 5000) and use
it from this application running on your **work Mac**. Encrypted end-to-end,
no port forwarding, no public exposure.

You will need:

- The Tailscale free tier ([tailscale.com](https://tailscale.com), one
  account, both machines logged in to it).
- Ollama installed on the Windows machine with at least one vision model
  pulled (`ollama pull moondream`, `ollama pull llama3.2-vision`, etc.).
- This app (`pw-demo-master`) running on the Mac.

---

## Part A — Home Windows machine (the Ollama host)

### 1. Make Ollama listen on all interfaces

By default Ollama only listens on `127.0.0.1`, which means even a tunneled
peer can't reach it. Set an environment variable so it binds to every
interface (the firewall rule in step 3 keeps it actually reachable only
from the tailnet).

1. Press **Win + R**, type `sysdm.cpl`, hit Enter.
2. **Advanced** tab → **Environment Variables…**.
3. Under **User variables**, click **New…**:
   - Variable name: `OLLAMA_HOST`
   - Variable value: `0.0.0.0:11434`
4. Click **OK** on every dialog.
5. Quit Ollama (right-click its system-tray icon → **Quit Ollama**), then
   relaunch it from the Start menu. The env var only applies to processes
   started after it was set.

Verify in PowerShell:

```powershell
netstat -ano | findstr 11434
```

You should see `0.0.0.0:11434` listening — not `127.0.0.1:11434`.

### 2. Install Tailscale

1. Download from [tailscale.com/download/windows](https://tailscale.com/download/windows).
2. Run the installer (it adds a system-tray icon).
3. Click the tray icon → **Log in**. Sign in with the email account you
   want to use (Google / GitHub / Microsoft / email).
4. After login the tray icon turns blue and shows your tailnet name.

Find this machine's Tailscale hostname — click the tray icon → **This
device**. It looks something like `desktop-0r1gos9` or whatever the
computer name is. **Write it down.** You'll paste it into the Mac later.

### 3. Add a firewall rule (so only the tailnet can hit Ollama)

Open **PowerShell as Administrator** and run:

```powershell
New-NetFirewallRule -DisplayName "Ollama (Tailscale only)" `
                    -Direction Inbound `
                    -LocalPort 11434 `
                    -Protocol TCP `
                    -Action Allow `
                    -RemoteAddress 100.64.0.0/10
```

`100.64.0.0/10` is the CGNAT range Tailscale uses for all peers — locking
inbound 11434 to that range means random LAN devices, Wi-Fi guests, etc.
can't reach Ollama. Only your tailnet can.

### 4. Sanity check on Windows itself

```powershell
curl http://localhost:11434/api/tags
```

Should return JSON listing your installed models (`moondream:latest`, etc.).
If this fails, Ollama isn't running or the env var didn't take — restart
Ollama.

---

## Part B — Work Mac (where this app runs)

### 1. Install Tailscale

Pick one:

- App Store: search "Tailscale", install.
- Or Homebrew: `brew install --cask tailscale`.

Launch it from `/Applications`, click the menubar icon → **Log in**. Sign
in to **the same account** you used on Windows.

### 2. Verify the home machine is visible

Click the Tailscale menubar icon. Your tailnet appears, listing both
devices with green/orange dots. The Windows machine should be there with
the hostname you noted in Part A step 2.

From a terminal on the Mac:

```bash
ping <your-windows-hostname>
```

(replace `<your-windows-hostname>` with the actual name, e.g.
`desktop-0r1gos9`)

You should get replies from a `100.x.y.z` address. If `ping` works but you
care about hostname resolution: Tailscale's **MagicDNS** is enabled by
default on free tier — confirm at
[login.tailscale.com/admin/dns](https://login.tailscale.com/admin/dns).

### 3. Check Ollama is reachable

```bash
curl http://<your-windows-hostname>:11434/api/tags
```

Same JSON output as the Windows-localhost test in Part A. If you get
"connection refused" — Windows firewall rule (step A.3) is missing or the
env var (step A.1) didn't apply.

---

## Part C — Point this app at the remote Ollama

1. Open the app in your browser (Mac).
2. **Settings** → **Ollama (local vision)** card.
3. Paste the URL into **Ollama base URL**:

   ```
   http://<your-windows-hostname>:11434
   ```

   (Use HTTP, not HTTPS — Ollama doesn't terminate TLS, and Tailscale is
   already encrypting the connection underneath.)

4. Click **Save & test**.
5. Expected feedback: `Connected (v0.x.y).` followed by "Installed models:"
   and a list of your pulled models.

### Use it in a rule

1. **AI-Camera → Rules → + New rule**.
2. In **Vision model**, pick one of the `Ollama · <name>` entries —
   e.g. `Ollama · moondream:latest`.
3. Fill in cameras, rule text, scan pattern, save.
4. On the next iteration the snapshot popup will show
   `Model: ollama · moondream:latest`, proving the call went to your home
   GPU.

The same dropdown is in **AI-Camera → Playground** if you want to test
ad-hoc without saving a rule.

---

## Troubleshooting

**"Connection refused" from the Mac**
- Ollama isn't running on Windows, OR
- `OLLAMA_HOST` env var didn't apply (restart Ollama after setting it), OR
- Windows Firewall is blocking 11434 (re-check the rule from A.3).

**"Connection timed out"**
- Tailscale isn't running on one of the machines (check menubar / tray).
- The Windows machine is asleep. Tailscale only works while the host is
  awake. Either disable sleep, or use Wake-on-LAN if you've set it up.

**"Ollama URL not configured" inside this app even after saving**
- Check the URL you pasted doesn't end with a trailing slash and uses
  `http://` not `https://`.

**First call is very slow, later calls are fast**
- Normal — Ollama loads model weights into VRAM on first request, and
  unloads them after a few minutes of idle. To keep a model "warm",
  pin it: in PowerShell on the Windows machine,
  `ollama run moondream` (leave it running in a terminal).

**Want to remove the Mac's access**
- Tailscale admin console → **Machines** → click the Mac → **Remove**.
  The Windows firewall rule stays; only your tailnet peers can hit
  Ollama, and the Mac is no longer a peer.

**Want to lock down even more**
- Enable **Tailnet Lock** at
  [login.tailscale.com/admin/settings/tailnet-lock](https://login.tailscale.com/admin/settings/tailnet-lock).
  Adding a new device then requires signing approval from an already-trusted
  device — defeats a stolen-credential attacker silently adding a rogue node.

---

## Why Tailscale and not Cloudflare Tunnel

Cloudflare Tunnel exposes Ollama at a public domain like
`ollama.yourdomain.com`. Ollama has **no authentication** — without
Cloudflare Access in front of it, anyone who guesses the URL owns your
GPU. Access protects browsers via cookies, but this app's backend calls
Ollama server-to-server, which means we'd have to extend the Ollama client
in [services/ollama.py](backend/app/services/ollama.py) to send
`CF-Access-Client-Id` / `CF-Access-Client-Secret` headers from a service
token.

Tailscale skips all of that: nothing is on the public internet, and no
code in this repo needs to change.
