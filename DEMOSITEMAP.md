# Vertical Demos — Sitemap & Plan

Five self-contained vertical demo apps, hosted alongside the existing PW
Demo Master admin app. Each demo proves the productized version of the
Live Representative system for one industry vertical, with its own
branding, login, dashboard, settings page, dummy database, and Live Rep
persona / KB / info-collection schema.

This is a **demo product**, not a real multi-tenant SaaS. One client demo
per vertical, hardcoded credentials, JSON-file "databases", no real auth /
RBAC / billing. The architecture is deliberately minimal so we can ship
five convincing client walkthroughs without rebuilding the foundation.

---

## 1. Verticals (initial set)

| Vertical          | URL prefix                | Demo creds         |
| ----------------- | ------------------------- | ------------------ |
| Gym               | `/demo/gym`               | `demo / demo`      |
| Restaurant        | `/demo/restaurant`        | `demo / demo`      |
| School            | `/demo/school`            | `demo / demo`      |
| Clinic            | `/demo/clinic`            | `demo / demo`      |
| Property Developer| `/demo/developer`         | `demo / demo`      |

Future verticals slot in as additional siblings under `/demo/<slug>`;
nothing in the architecture is per-vertical-count-dependent.

---

## 2. Architecture — agreed decisions

- **No shared chrome.** Each vertical renders as its own self-contained
  app — its own `index.html`, `app.js`, `styles.css`, brand colors,
  logo, sidebar, fonts. The Primewave admin app at `/` is unrelated and
  stays untouched.
- **URL shape:** `/demo` is a tiny landing page (5 cards). Each vertical
  lives at `/demo/<slug>/login`, `/demo/<slug>/dashboard`,
  `/demo/<slug>/settings`, `/demo/<slug>/live-rep` (and whatever else
  that vertical needs). All assets served as static files under
  `/demo/<slug>/`.
- **Auth:** session cookies *scoped to `/demo/<slug>`* so logging into
  one demo doesn't authenticate you on another. Hardcoded creds, no
  user CRUD, no password hashing — this is a demo.
- **Dummy database:** one JSON file per vertical at
  `data/demos/<slug>.json`, seeded from `seed.json` on first run.
  Mutations write back to the same file. No SQL, no migrations.
- **Per-vertical config (persona / KB / info-schema / brand):** baked
  into `backend/app/demos/<slug>/config.py`. The vertical's own
  Settings page reads/writes this config; the global `slr_*` settings
  on the existing Live Rep page are unaffected.
- **Live Rep wiring (preferred):** single AudioSocket service, dialplan
  encodes the vertical in the AudioSocket UUID prefix
  (`gym-demo-...`, `restaurant-demo-...`, etc.). The backend reads the
  UUID prefix on call accept and loads that vertical's persona /
  KB / schema for the Gemini Live session. One port, five demos,
  zero process duplication.
  - **Alternative:** five separate AudioSocket ports (8092–8096), one
    per vertical, each with its own static config. Easier to reason
    about, more memory. Decide before phase 3.

---

## 3. Per-vertical scope (what every demo ships with)

Every vertical mini-app includes the same pages, just with vertical-
specific content, widgets, and theme:

1. **Login page** — branded, single form, hardcoded creds.
2. **Dashboard** — vertical-specific widgets reading from the dummy DB:
   recent activity, KPIs, vertical-specific entity tables (members,
   reservations, students, patients, leads).
3. **Live Representative** — per-vertical persona + KB + info-collection
   schema. Same call-history / collected-info / accuracy plumbing as
   the existing Live Rep page, but scoped to this vertical's data file
   (call records flow into the vertical's DB so dashboards can show
   them).
4. **Settings** — edit this vertical's persona, KB, info-schema, brand
   colors, demo creds. Writes to `data/demos/<slug>.json`.
5. **(optional, per vertical)** mini-CRM views: edit/add/delete entities,
   inline notes, follow-up flags.

### Vertical-specific widget ideas (initial drafts — refine per demo)

| Vertical          | Dashboard widgets                                                                |
| ----------------- | -------------------------------------------------------------------------------- |
| Gym               | Members, today's classes, trial-pass requests, monthly check-ins                 |
| Restaurant        | Today's reservations, table availability, kitchen orders, top-selling items     |
| School            | Students, attendance, parent inquiries, fee status                               |
| Clinic            | Today's appointments, patient queue, prescriptions, follow-up calls due          |
| Property Developer| Leads pipeline, available units, scheduled viewings, sales funnel               |

Info-collection schema (Live Rep) per vertical — examples:

- **Gym:** name, phone, fitness goal, preferred trial date.
- **Restaurant:** name, party size, date/time, dietary notes.
- **School:** parent name, child name, grade level, contact, inquiry topic.
- **Clinic:** patient name, phone, symptom summary, preferred doctor.
- **Property Developer:** name, contact, budget range, unit type interest.

---

## 4. File / folder layout

### Backend

```
backend/app/
  demos/
    __init__.py
    auth.py                 # demo session cookies, login helpers
    landing.py              # GET /demo (5-card landing)
    common/
      db.py                 # load_db(slug) / save_db(slug) — JSON file
      live_rep.py           # vertical-aware Gemini Live wrapper
                            #   (or hook into existing services/sip_live_rep.py
                            #    that branches on UUID prefix)
    gym/
      __init__.py
      router.py             # all gym endpoints under /api/demo/gym/*
      config.py             # persona, KB, info_schema, brand, creds
      seed.json             # initial dummy data
    restaurant/  ... same shape
    school/      ... same shape
    clinic/      ... same shape
    developer/   ... same shape
```

### Frontend

```
frontend/demos/
  index.html                # /demo landing page (5 cards)
  styles.css                # landing-only styles
  gym/
    index.html              # full self-contained SPA shell
    app.js
    styles.css
    assets/
      logo.svg
  restaurant/  ... same shape
  school/      ... same shape
  clinic/      ... same shape
  developer/   ... same shape
```

### Data

```
data/
  demos/
    gym.json
    restaurant.json
    school.json
    clinic.json
    developer.json
```

`data/demos/` is gitignored along with the existing `data/` rule.
`seed.json` (checked in, inside each vertical's backend folder) is the
template; first request creates the live data file from it.

---

## 5. Phased plan

Each phase ships a demo that you can show to a client by itself.

### Phase 0 — decisions (no code)

- Lock the Live Rep wiring model (single UUID-routed port vs. five
  ports). Default to **UUID-routed single port** unless we hit a
  blocker.
- Pick the **first vertical** to build end-to-end (recommend **Gym** —
  simple data model, clear "leads + classes" structure).
- Sign off on the per-vertical brand direction (rough colors + logo
  approach: stylized text or generated SVG marks for the demo).

### Phase 1 — Foundations (~1 day)

- `backend/app/demos/` package skeleton.
- `auth.py` — session cookie middleware (signed cookie, scoped path).
- `common/db.py` — load/save JSON with the seed-on-first-run pattern.
- `landing.py` — `/demo` 5-card page listing the verticals.
- Each vertical's `router.py` registered but only exposing `/login`,
  `/me`, `/logout`. Dashboard returns "Coming soon" placeholder.
- Each vertical's `index.html` + minimal themed shell (no widgets yet).
- Wire `backend/app/main.py` to mount the demos router + static files.
- Hardcoded creds work, session round-trip works, dashboard renders
  with a "Welcome, demo" greeting.

**Deliverable:** all five logins work, all five dashboards open empty
with their own colors / fonts / logo.

### Phase 2 — One vertical, end-to-end (~2–3 days)

Pick one vertical (default: **Gym**). Build everything for it:

- Dashboard widgets driven by `data/demos/gym.json`.
- Mini-CRM: members table, today's classes, trial-pass requests.
- Settings page wired to `config.py` (persona / KB / info-schema /
  brand / creds editable from the UI, persisted to the JSON DB).
- Live Rep page scoped to this vertical's persona / KB / schema.
  Reuses the existing AudioSocket service but reads vertical-specific
  config based on the call's UUID prefix.
- Vertical-specific call-history view that pulls into the dashboard.

**Deliverable:** the Gym demo is client-ready. Login → branded dashboard
→ live phone call into Lena (now a gym receptionist persona) →
collected info shows up on the dashboard.

### Phase 3 — Clone to the other four verticals (~1 day each)

For each of Restaurant, School, Clinic, Developer:

- Duplicate the Gym vertical folder structure.
- Swap brand colors, logo, fonts.
- Customize widget set for that vertical.
- Customize seed data (sample members → sample reservations, etc.).
- Customize Live Rep persona, KB, info-schema.
- Hook up the dialplan extension and UUID prefix.

**Deliverable:** all five vertical demos client-ready and
distinguishable.

### Phase 4 — Polish (~1 day)

- Landing page redesign — visual mini-portfolio of the five demos with
  short pitches, screenshots, "Try it" buttons.
- README section explaining how to demo each vertical (which extension
  to dial, what credentials to use, what to look for on the dashboard).
- One-pager PDF / handout (optional — for client meetings).

---

## 6. Live Rep wiring — UUID-routed single port (preferred)

### How a call flows end-to-end

1. Client dials extension on FreePBX (one per vertical):
   - `9991` → Gym
   - `9992` → Restaurant
   - `9993` → School
   - `9994` → Clinic
   - `9995` → Developer
2. Dialplan for each extension sets a vertical-prefixed UUID and calls
   the same AudioSocket port:

   ```ini
   [pwdemo-gym]
   exten => s,1,NoOp(Gym demo)
    same => n,Answer()
    same => n,Set(AUDIOSOCKET_UUID=gym-demo-00000000-0000-0000-0000-000000000001)
    same => n,AudioSocket(${AUDIOSOCKET_UUID},192.168.100.89:8091)
    same => n,Hangup()
   ```
3. Backend `sip_live_rep.py` reads the UUID's prefix (`gym-demo-...`),
   looks up `backend/app/demos/gym/config.py`, and opens the Gemini
   Live session with that vertical's persona / KB / schema + voice.
4. `save_caller_information` tool calls land in
   `data/demos/<vertical>.json` under `leads[]`, with `vertical`,
   `call_id`, `ts`, and the schema fields. The vertical's dashboard
   reads from that array.

### Code changes required (Live Rep)

- New helper `resolve_vertical_from_uuid(uuid) -> str | None`.
- `_build_system_instruction()` and `_build_collect_tool()` switch on
  the resolved vertical: if `None`, fall back to the existing global
  `slr_*` state (preserves the current Lena-for-Primewave demo).
- `save_caller_information` handler also writes the collected record
  into the vertical's JSON DB, not just the call's transcript.

### Fallback: five separate ports

If UUID routing becomes a problem (it shouldn't), run five `Service`
instances on ports 8091–8095, each with a hardcoded vertical. Dialplan
points each extension at its dedicated port. Simpler but uses 5× the
memory and 5× the lifecycle bookkeeping.

---

## 7. Open decisions to lock before Phase 1

1. **First vertical to build end-to-end** — Gym (recommended) or other?
2. **Brand assets** — full design pass per vertical, or simple
   color-swap-and-text-logo for the demo?
3. **PBX extension numbers** — confirm `9991–9995` are free on the
   demo FreePBX, or pick alternatives.
4. **Dashboard density** — minimal (3 widgets) or full (8+) per
   vertical? Affects phase 2/3 effort estimates.
5. **Editable settings per vertical** — should the persona/KB be
   editable inside the demo (more impressive but more code), or fixed
   in `config.py` for the demo (faster to ship)?

---

## 8. What this plan deliberately doesn't do

- **No real authentication.** No bcrypt, no password reset, no user
  management. Demo-only creds in a config file.
- **No real multi-tenancy.** Each vertical = one demo customer. We
  don't model "schools" as a class with N schools inside it.
- **No SQL, no migrations.** JSON files are the database. Easy to
  reset, easy to inspect, easy to seed.
- **No billing / quotas / usage metering.** Out of scope for the demo.
- **No per-tenant Gemini API keys.** All five verticals share the
  global key configured in main app Settings.
- **No phone-number-per-customer.** All five verticals route through
  the same demo PBX, just via different extensions.

When the time comes to productize, the abstractions in place
(`demos/<slug>/config.py`, vertical-scoped DB, UUID-routed Live Rep)
are easy to lift into a real `tenants` table with per-row config and
per-tenant phone DIDs. The demo doesn't paint us into a corner.
