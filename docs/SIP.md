# Setting up a PBX in Proxmox for PW Demo Master

This guide walks you from a fresh Proxmox host to a working SIP PBX that the
**SIP Phone → Extension** page can register against. You'll end with two
extensions you can call between in two browser tabs.

Stack we use:

- **Proxmox VE 8.x** host
- **Debian 12 (Bookworm) LXC container** for the PBX (lighter than a VM and
  perfectly fine for Asterisk)
- **Asterisk 20** (in Debian repos) configured with `chan_pjsip`
- **WebRTC transport** (`wss://`, `ICE`, `DTLS-SRTP`, `rtcp-mux`) so JsSIP in
  the browser can register and place calls

Plain Asterisk + `.conf` files keeps the setup small, transparent, and easy
to copy between machines. If you'd rather use a GUI, see
[FreePBX alternative](#freepbx-alternative) at the bottom.

> ⚠️ **Browser requirements.** Any modern browser will refuse plain `ws://`
> SIP when the page itself is served over HTTPS. So you'll either run the
> PBX with a real TLS certificate (`wss://`) or run both the demo and the
> PBX over plain HTTP on a trusted LAN. The instructions below cover the
> `wss://` path — that's what production-shaped setups need.

---

## 1. Create the LXC container in Proxmox

### 1.1 Pull the Debian 12 template

In the Proxmox UI: **Datacenter → your-node → local (storage) → CT Templates → Templates**, find `debian-12-standard_*_amd64.tar.zst`, click **Download**.

Or from the Proxmox shell:

```bash
pveam update
pveam available | grep debian-12
pveam download local debian-12-standard_12.7-1_amd64.tar.zst   # name may differ
```

### 1.2 Provision the container

GUI: **Create CT** with these settings (adjust to taste):

| Setting | Value |
| --- | --- |
| Hostname | `pbx` |
| Unprivileged | ☐ unticked (**privileged**) — saves time with PJSIP / sockets |
| Disk | 8 GB (local-lvm) |
| Cores | 2 |
| Memory | 1024 MB |
| Swap | 512 MB |
| Network | `vmbr0`, **static IP** (e.g. `192.168.1.50/24`), gateway `192.168.1.1` |
| Nameservers | your LAN DNS (e.g. `192.168.1.1`) or `1.1.1.1` |
| Start on boot | ✓ |
| Unprivileged → Features | `nesting=1` is fine but not required |

If you prefer the shell:

```bash
pct create 200 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname pbx \
  --cores 2 --memory 1024 --swap 512 \
  --rootfs local-lvm:8 \
  --net0 name=eth0,bridge=vmbr0,ip=192.168.1.50/24,gw=192.168.1.1 \
  --nameserver 192.168.1.1 \
  --unprivileged 0 \
  --onboot 1
pct start 200
pct enter 200
```

> Why privileged? Asterisk drops privileges to its own user automatically;
> we don't need root inside the container at runtime. Privileged just
> avoids small headaches with `cap_net_bind_service`, sockets, and AppArmor.

### 1.3 Pick a hostname you'll use in the TLS cert

The browser must trust the cert that the PBX presents on its `wss://`
endpoint. Either:

- **Public DNS name** (e.g. `pbx.example.com`) pointing at the container's
  public IP — needed for Let's Encrypt.
- **Local DNS name** (e.g. `pbx.lan`) + a self-signed cert imported into
  every browser that will use it.

Pick one now — you'll use it everywhere below as `PBX_HOST`.

---

## 2. Base packages and timezone

> ⚠️ **Asterisk packaging across distros is a mess.** Asterisk was dropped
> from **Debian 12** (no maintainer through the freeze) and from
> **Ubuntu 22.04 LTS** (which pulls from Debian). On a stock install of
> either, `apt install asterisk` fails with
> `E: Package 'asterisk' has no installation candidate`.
>
> Pick one of the three paths below. **Path A (source build)** is the most
> portable and is what we recommend — works on any LXC base, gives you
> Asterisk 20 LTS, and it's a single block of paste.

### Path A — Build Asterisk 20 from source (recommended)

Works on any Debian/Ubuntu LXC. Takes ~15 minutes; Asterisk's bundled
`install_prereq` script installs every apt dependency for you.

```bash
apt update
apt -y install build-essential git wget tar pkg-config autoconf \
                ssl-cert dnsutils curl ca-certificates ufw chrony

cd /usr/src
wget https://downloads.asterisk.org/pub/telephony/asterisk/asterisk-20-current.tar.gz
tar -xzf asterisk-20-current.tar.gz
cd asterisk-20.*/

./contrib/scripts/install_prereq install
./configure --with-pjproject-bundled --with-jansson-bundled
make menuselect.makeopts
make -j"$(nproc)"
make install
make samples
make config
ldconfig
systemctl daemon-reload
systemctl enable --now asterisk

timedatectl set-timezone Europe/London    # or wherever you are
asterisk -V                                # confirm "Asterisk 20.x.x"
systemctl stop asterisk                    # we'll restart after config edits
```

### Path B — Debian 11 (Bullseye) LXC

If you provisioned the container as **Debian 11**, Asterisk is still in the
main repo:

```bash
apt update && apt -y upgrade
apt -y install asterisk asterisk-core-sounds-en \
                ssl-cert dnsutils curl ca-certificates ufw chrony
timedatectl set-timezone Europe/London
systemctl stop asterisk
```

### Path C — bookworm-backports (Debian 12 only)

Worth trying on Debian 12 if Path A feels heavy. Doesn't always work —
the backports package occasionally lags and gets removed:

```bash
echo "deb http://deb.debian.org/debian bookworm-backports main" \
  > /etc/apt/sources.list.d/bookworm-backports.list
apt update
apt -y install -t bookworm-backports asterisk asterisk-core-sounds-en
```

If you see `Package 'asterisk' has no installation candidate` even with
backports enabled, fall back to Path A.

### Path D — Proxmox VM (instead of LXC)

A VM dodges LXC packaging quirks entirely (Asterisk has full control of
its own kernel and namespaces) at the cost of ~1 GB extra RAM and a bit
of extra disk. Two flavours:

- **D1 — Debian 12 VM** then build Asterisk 20 from source (effectively
  Path A but in a VM). Use this if you want full control and minimal
  footprint.
- **D2 — FreePBX Distro VM** (Sangoma 7 / CentOS-based ISO, preinstalled
  with Asterisk + Apache + MariaDB + the FreePBX web UI). Use this if you
  want a GUI to manage extensions and TLS without editing `.conf` files.

#### Common: provisioning the VM in Proxmox

In the Proxmox UI: **Create VM** with these settings (any values not
mentioned can stay at their defaults):

| Step | Setting | Value |
| --- | --- | --- |
| General | Name | `pbx` |
| OS | ISO image | `debian-12.x.x-amd64-netinst.iso` (D1) **or** `FreePBX-…-x86_64-Full.iso` (D2) |
| OS | Type / Version | Linux / 6.x – 2.6 Kernel |
| System | Machine | `q35` |
| System | BIOS | **Default (SeaBIOS)** |
| System | SCSI Controller | VirtIO SCSI single |
| System | Qemu Agent | ✓ tick |
| Disks | Bus/Device | SCSI |
| Disks | Disk size | **8 GB** for D1, **20 GB** for D2 |
| Disks | Discard | ✓ tick (frees space when files are deleted) |
| CPU | Cores | 2 |
| CPU | Type | `host` (best perf — only matters if you migrate cross-CPU) |
| Memory | Size | **1024 MB** for D1, **2048 MB** for D2 |
| Network | Bridge | `vmbr0` |
| Network | Model | VirtIO (paravirtualized) |
| Confirm | Start after created | ✓ tick |

ISO downloads:

- Debian 12 netinst: <https://www.debian.org/distrib/netinst>
- FreePBX Distro: <https://www.freepbx.org/downloads/freepbx-distro/> (the
  "Stable" ISO, currently SangomaOS 7).

Upload either ISO to a Proxmox storage that supports `Container template /
ISO image` content (typically `local`), then attach it in the **OS** step
of the wizard.

#### D1 — Debian 12 VM (Asterisk from source)

1. Boot the VM into the Debian netinst installer. Choose **Install** (not
   "Graphical install" — text installer is faster over noVNC).
2. During package selection deselect everything except **standard system
   utilities** and **SSH server**. You don't need a desktop, web server,
   or print server.
3. After reboot, log in over SSH (the installer will have shown you the
   IP), then run the **same Path A source-build script** above. Skip the
   bookworm-backports lines — they don't apply to a VM either.
4. Continue from §3 (TLS certificate) — every config path in this guide
   is identical between LXC and VM.

#### D2 — FreePBX Distro VM (GUI-driven PBX)

1. Boot the VM from the FreePBX Distro ISO. The installer is a guided
   text UI; pick "FreePBX Standard". It auto-partitions the disk and
   installs everything (≈ 15-20 minutes).
2. On first boot the console shows a one-liner URL like
   `http://<vm-ip>` — open it in a browser, set the admin email and
   password to finish setup.
3. **Enable the WebSocket transport:**
   - **Settings → Asterisk SIP Settings → SIP Settings [chan_pjsip]**
   - "Enable Transport WSS" → yes, bind port `8089`.
   - Upload the TLS cert + key (use **Admin → Certificate Management**
     first; FreePBX can generate Let's Encrypt certs natively if the PBX
     has a public DNS name).
4. **Create a WebRTC extension:**
   - **Applications → Extensions → Add Extension → PJSIP Extension**
   - User Extension `1001`, set a secret password.
   - **Advanced** tab: Transport = `0.0.0.0-wss`, **Enable WebRTC** ✓
     (FreePBX flips DTLS, AVPF, ICE, and rtcp-mux for you).
5. **Apply Config** (red bar at the top right) — required after any change.
6. Repeat (4) for extension `1002`.
7. Jump to **§7 Wire the PBX into PW Demo Master**. Skip §3, §4, §5, §6 —
   FreePBX handles all of those for you.

> If you go the D2 route, you can ignore everything in §3 through §6 of
> this guide. The "FreePBX alternative" appendix at the very bottom of
> this file expands on a few non-default knobs you may want to flip
> (codec ordering, RTP range, NAT settings) once the basic setup works.

---

`chrony` matters: TLS will fail if the container/VM clock drifts more
than a few minutes from `Now()`. Path A installs it; Paths B/C/D1 install
it explicitly in the apt line above; FreePBX Distro (D2) already includes
NTP sync out of the box.

Stop Asterisk for now so we can drop our config in cleanly:

```bash
systemctl stop asterisk
systemctl disable asterisk    # we'll re-enable after the config is done
```

---

## 3. TLS certificate for the WebSocket transport

Pick **one** of these.

### 3.1 Option A — Let's Encrypt (public DNS)

```bash
apt -y install certbot
certbot certonly --standalone -d $PBX_HOST
```

Cert lives at `/etc/letsencrypt/live/$PBX_HOST/`. Make Asterisk able to
read it:

```bash
groupadd -f tlsread
usermod -aG tlsread asterisk
chgrp -R tlsread /etc/letsencrypt/{live,archive}
chmod -R g+rX /etc/letsencrypt/{live,archive}
```

Auto-renew + reload Asterisk:

```bash
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/asterisk.sh <<'EOF'
#!/bin/sh
chgrp -R tlsread /etc/letsencrypt/live /etc/letsencrypt/archive
chmod -R g+rX  /etc/letsencrypt/live /etc/letsencrypt/archive
systemctl reload asterisk
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/asterisk.sh
```

Paths to remember:

- Cert chain: `/etc/letsencrypt/live/$PBX_HOST/fullchain.pem`
- Private key: `/etc/letsencrypt/live/$PBX_HOST/privkey.pem`

### 3.2 Option B — Self-signed local CA (no public DNS)

Generate a 10-year self-signed cert for `pbx.lan` (or whatever local name
you chose). Put it in `/etc/asterisk/keys/`:

```bash
mkdir -p /etc/asterisk/keys && cd /etc/asterisk/keys
openssl req -x509 -newkey rsa:4096 -nodes \
  -days 3650 \
  -subj "/CN=$PBX_HOST" \
  -addext "subjectAltName=DNS:$PBX_HOST,IP:192.168.1.50" \
  -keyout asterisk.key -out asterisk.crt
chown -R asterisk:asterisk /etc/asterisk/keys
chmod 640 asterisk.key
```

Then on every machine that will run the demo, **import `asterisk.crt`** into
the OS trust store (macOS Keychain "System" → trust for SSL; Windows
"Trusted Root Certification Authorities"). Browsers reuse the OS trust
store and will accept `wss://pbx.lan:8089/ws`.

Paths to remember:

- Cert: `/etc/asterisk/keys/asterisk.crt`
- Key:  `/etc/asterisk/keys/asterisk.key`

---

## 4. Asterisk core config

We're replacing only the files we need. Asterisk reads `/etc/asterisk/*.conf`.

### 4.1 `pjsip.conf` — transports, endpoints, AORs, auth

This is the only file that changes between deployments. Copy this as
`/etc/asterisk/pjsip.conf`, edit the highlighted lines.

```ini
; ============================================================
; Transports
; ============================================================
[transport-udp]
type=transport
protocol=udp
bind=0.0.0.0:5060

[transport-wss]
type=transport
protocol=wss
bind=0.0.0.0:8089
cert_file=/etc/letsencrypt/live/PBX_HOST/fullchain.pem    ; ← Option A
priv_key_file=/etc/letsencrypt/live/PBX_HOST/privkey.pem  ; ← Option A
; cert_file=/etc/asterisk/keys/asterisk.crt               ; ← Option B
; priv_key_file=/etc/asterisk/keys/asterisk.key           ; ← Option B
method=tlsv1_2

; ============================================================
; Template for any WebRTC endpoint — both 1001 and 1002 inherit this.
; Settings ride or die for browser interop: DTLS-SRTP, AVPF, ICE,
; rtcp-mux, force_rport, rewrite_contact.
; ============================================================
[webrtc-endpoint](!)
type=endpoint
context=internal
disallow=all
allow=opus
allow=ulaw
allow=alaw
webrtc=yes                     ; sets the rest of the WebRTC quirks
use_avpf=yes
media_encryption=dtls
dtls_auto_generate_cert=yes
dtls_verify=fingerprint
dtls_setup=actpass
ice_support=yes
rtcp_mux=yes
force_rport=yes
rewrite_contact=yes
direct_media=no
trust_id_inbound=yes

[webrtc-aor](!)
type=aor
max_contacts=1
remove_existing=yes

[webrtc-auth](!)
type=auth
auth_type=userpass

; ============================================================
; Extension 1001
; ============================================================
[1001](webrtc-endpoint)
auth=1001-auth
aors=1001-aor

[1001-auth](webrtc-auth)
username=1001
password=Change-Me-1001

[1001-aor](webrtc-aor)

; ============================================================
; Extension 1002
; ============================================================
[1002](webrtc-endpoint)
auth=1002-auth
aors=1002-aor

[1002-auth](webrtc-auth)
username=1002
password=Change-Me-1002

[1002-aor](webrtc-aor)
```

Replace `PBX_HOST`, `Change-Me-1001`, and `Change-Me-1002` with your real
values.

### 4.2 `http.conf` — required to bind the WebSocket

`chan_pjsip` shares the built-in HTTP listener. Edit
`/etc/asterisk/http.conf`:

```ini
[general]
enabled=yes
bindaddr=0.0.0.0
bindport=8088              ; plain HTTP — we won't actually expose this
tlsenable=yes
tlsbindaddr=0.0.0.0:8089
tlscertfile=/etc/letsencrypt/live/PBX_HOST/fullchain.pem
tlsprivatekey=/etc/letsencrypt/live/PBX_HOST/privkey.pem
```

(Same cert paths as `pjsip.conf`. For Option B, swap to the `/etc/asterisk/keys/...` paths.)

### 4.3 `extensions.conf` — dialplan

Keep it simple: in the `internal` context, dial whichever PJSIP endpoint
matches the dialled number.

```ini
[general]
static=yes
writeprotect=no

[globals]

[internal]
exten => _1XXX,1,NoOp(Internal call from ${CALLERID(num)} to ${EXTEN})
 same => n,Dial(PJSIP/${EXTEN},20)
 same => n,Hangup()

exten => _9XX,1,NoOp(Test extension)
 same => n,Answer()
 same => n,Wait(1)
 same => n,Playback(hello-world)
 same => n,Hangup()
```

After this, `1001` dials `1002` and vice-versa; `999` plays the "hello world"
prompt back at you (handy for one-tab testing — you only need to register
one extension to hear audio play).

### 4.4 `rtp.conf` — UDP media port range

Defaults are fine for LAN. Verify `/etc/asterisk/rtp.conf` has:

```ini
[general]
rtpstart=10000
rtpend=20000
```

### 4.5 `logger.conf` — make debugging easier

`/etc/asterisk/logger.conf` (overwrite):

```ini
[general]
[logfiles]
console = notice,warning,error,verbose,dtmf
messages = notice,warning,error
```

---

## 5. Open the firewall

`ufw` is already installed.

```bash
ufw allow 22/tcp                  # SSH
ufw allow 8089/tcp                # SIP-over-WebSocket (TLS)
ufw allow 5060/udp                # SIP UDP (optional, for non-WebRTC clients)
ufw allow 10000:20000/udp         # RTP media
ufw --force enable
```

If the demo client is on the same LAN you're done. If it's behind NAT
(e.g. accessing the PBX over the internet), also add to `pjsip.conf` →
`[transport-wss]`:

```ini
external_media_address=YOUR.PUBLIC.IP
external_signaling_address=YOUR.PUBLIC.IP
local_net=192.168.1.0/24
```

…and forward the same ports on the upstream router.

---

## 6. Start Asterisk, sanity-check

```bash
systemctl enable --now asterisk
asterisk -rvvv             # opens the Asterisk CLI
```

Inside the CLI:

```
pbx*CLI> pjsip show transports
pbx*CLI> pjsip show endpoints
pbx*CLI> pjsip show endpoint 1001
```

You should see `wss` transport bound on `0.0.0.0:8089` and endpoints
`1001` / `1002` in `Unavailable` (no contact yet — expected until a client
registers).

For live signalling tracing while you debug:

```
pbx*CLI> pjsip set logger on
```

`Ctrl+C` exits the CLI without stopping Asterisk.

### 6.1 Confirm the WSS endpoint from another machine

From your laptop:

```bash
# Just a TCP probe — does port 8089 respond?
nc -zv $PBX_HOST 8089

# TLS handshake — does the cert look right?
openssl s_client -connect $PBX_HOST:8089 -servername $PBX_HOST </dev/null \
  | openssl x509 -noout -subject -issuer -dates
```

For Option B (self-signed) the issuer will be yourself; for Option A
(Let's Encrypt) the issuer is `R3`/`R10`/`R11`/etc.

---

## 7. Wire the PBX into PW Demo Master

In the demo app:

1. **Settings → SIP softphone**
   - WebSocket URL: `wss://PBX_HOST:8089/ws`
   - Extension: `1001`
   - Password: `Change-Me-1001` (whatever you put in `pjsip.conf`)
   - SIP realm: leave blank (auto-derived from the WS host)
   - Display name: anything, e.g. `Reception`
   - **Save**
2. **SIP Phone → Extension**
   - The page auto-loads the credentials from the backend and starts
     JsSIP. Within ~1s the topbar pill flips to `SIP: Registered · 1001`.

To test end-to-end **without a second device**, dial `999` — Asterisk
answers and plays a "Hello world" prompt over your speakers/headphones.

For a two-party call, open a **second browser tab** (or a second browser
entirely — Chrome and Firefox count as separate user agents), go to
Settings, change the Extension to `1002` and Password to the matching one,
save, then open the Extension page. Now tab #1 dials `1002`, tab #2 sees
the incoming-call modal, accept → you've got a full-duplex WebRTC call
through the PBX. 🎉

---

## 8. Common failure modes

### TLS error in the browser (`net::ERR_CERT_AUTHORITY_INVALID`)
The browser doesn't trust the cert.
- Option A users: confirm the cert chain returned by `openssl s_client`
  matches the public name in the WS URL. Visit `https://PBX_HOST:8089/ws`
  in the address bar — the browser will show the underlying TLS error.
- Option B users: you skipped importing `asterisk.crt` into the OS trust
  store. Browsers will not accept a self-signed cert via "Accept once" for
  WebSocket connections — it has to be in the trust store.

### `register_failed` with cause `Connection Error`
WS can't reach the server. Check:
1. `ufw status` includes 8089/tcp.
2. `pjsip show transports` lists `wss`.
3. From your laptop: `nc -zv PBX_HOST 8089`.

### `register_failed` with cause `401 Unauthorized`
Wrong password, or the `[NNNN-auth]` block doesn't match the endpoint.
Look for the actual error in the Asterisk CLI with `pjsip set logger on`.

### Audio one-way or no audio
RTP isn't reaching the browser. Either the firewall is blocking
10000–20000/udp, or your PBX is behind NAT and you didn't set
`external_media_address`. Use Chrome `chrome://webrtc-internals/` while a
call is up — ICE candidates and selected pair are the smoking gun.

### "DTLS handshake failed" in CLI logs
Almost always a TLS cert problem on the *PBX* side (the WSS one). Verify
`pjsip.conf` `[transport-wss]` paths exist and Asterisk can read them
(`sudo -u asterisk cat /etc/letsencrypt/live/.../fullchain.pem`).

### "ICE failed"
Browser couldn't pair candidates with Asterisk. Common when you forgot
`ice_support=yes` and `rtcp_mux=yes` on the endpoint, or when STUN is
blocked. The browser side uses `stun:stun.l.google.com:19302` by default
(see [frontend/sip-phone.js](../frontend/sip-phone.js)); for fully-internal
LAN setups you don't actually need STUN.

### Asterisk dies after a config reload
Run `asterisk -cvvvg` (foreground, verbose, never daemonize) to see the
actual crash. 99% of the time it's a typo in `pjsip.conf` — Asterisk's
parser will tell you the file + line.

---

## FreePBX alternative

If you'd rather drive the PBX from a web UI, install FreePBX instead of
plain Asterisk. The simplest path on a fresh Debian 12 LXC:

```bash
wget https://mirror.freepbx.org/modules/release/sng7/sng7-pbx-installer-latest.sh
bash sng7-pbx-installer-latest.sh
```

After it finishes, browse to `http://PBX_HOST` to complete setup.

For the **demo's SIP page** to register, in FreePBX:

1. **Settings → Asterisk SIP Settings → SIP Settings [chan_pjsip]**
   - "Enable Transport WSS" = yes
   - Bind port 8089
   - Upload your TLS cert (Admin → Certificate Management first)
2. **Applications → Extensions → Add Extension → PJSIP Extension**
   - User Extension `1001`, password
   - **Advanced**: Transport = `0.0.0.0-wss`, enable WebRTC (sets DTLS,
     AVPF, ICE, rtcp-mux automatically)
3. Apply Config (the big red button at top right).

Then point PW Demo Master's SIP Settings at `wss://PBX_HOST:8089/ws` with
extension `1001` and the password you set. Everything else (dialling,
in-call UI) works the same — the page doesn't care which Asterisk-flavoured
PBX is on the other end as long as the WebRTC quirks are configured.

---

## What we deliberately didn't cover

- **Trunks to the PSTN** (SIP trunks at your VoIP carrier). Not relevant
  for the demo — extensions calling each other is enough to prove the
  Live Agent voice path later.
- **Voicemail**. Add later if you want a place for missed calls to land.
- **HA (High Availability)**. Not a thing for a demo PBX.
- **Encrypting RTP without DTLS-SRTP**. WebRTC requires DTLS-SRTP; don't
  try to use SDES-SRTP or plain SRTP for the browser leg.

Once this works end-to-end, the next step is wiring the **Smart Home →
Live Agent** Gemini session into a server-side SIP UA that registers as
its own extension and bridges audio to Gemini Live. That's a separate
piece in `backend/app/services/` and lives outside this guide.
