# Vertical Demos — Sitemap & Plan

Six self-contained vertical demo apps, hosted alongside the existing PW
Demo Master admin app. Each demo proves the productized version of the
Live Representative system for one industry vertical, with its own
branding, login, dashboard, settings page, dummy database, and Live Rep
persona / KB / info-collection schema.

This is a **demo product**, not a real multi-tenant SaaS. One client demo
per vertical, hardcoded credentials, JSON-file "databases", no real auth /
RBAC / billing. The architecture is deliberately minimal so we can ship
six convincing client walkthroughs without rebuilding the foundation.

## Design source

Per-vertical UI designs are authored in **Lovable** and exported to a
GitHub repo (one repo per vertical, delivered to us in sequence —
Clinic first).

**Ingestion model — locked: ship the React build as-is.** The Lovable
output (React + Vite + Tailwind + shadcn/ui) is **built once per design
update** and the `dist/client/` folder is copied into
`frontend/demos/<slug>/`. FastAPI serves the resulting static files —
no Vite, no Node, no bundler at runtime. The "no build step" rule in
CLAUDE.md applies to the serving path and the admin app; it doesn't
preclude a one-time build that produces the static assets we deploy.

Why not translate to vanilla:

- Tailwind utility classes, shadcn/ui component variants, motion, and
  theme tokens never translate 1:1. Pixel-perfect fidelity matters here
  because the demos are sales artefacts.
- Each vertical's React app is self-contained at `/demo/<slug>/*` —
  it doesn't share state with the admin app, so there's no JS bridge
  to maintain.

What the React app needs to know:

- The router runs in SPA mode so `/dashboard`, `/clinics` etc. resolve
  under the vertical's path. For TanStack Start (Clinic), this is done
  via `tanstackStart: { spa: { enabled: true, prerender: { outputPath:
  "index.html" } } }` in `vite.config.ts` so the build produces a real
  `index.html` with hydration markers — without it `hydrateRoot` bails
  silently and the page renders blank.
- All API calls hit `/api/demo/<slug>/*` (our backend). The session
  cookie is **per-slug-named** (`pw_demo_clinic`, `pw_demo_restaurant`,
  …) at path `/` so verticals coexist in the same browser without
  authenticating each other.
- Vite `base: '/demo/<slug>/'` so built asset URLs resolve correctly.
- Cloudflare bundling is disabled (`cloudflare: false`) since we ship
  as a SPA mounted inside the admin app, not as a Workers deployment.

The Clinic build/redeploy step (run from the Lovable repo root):

```bash
cd lovable-clinic && rm -rf dist && npm run build \
  && rm -rf ../pw-demo-master/frontend/demos/clinic/* \
  && cp -r dist/client/* ../pw-demo-master/frontend/demos/clinic/
```

---

## Two-machine source-of-truth state

We work on this project from **two machines**, syncing the PWDemoMaster
repo (FastAPI backend + admin app + built clinic SPA) over git. The
per-vertical Lovable source repos are *separate* — they live as siblings
of PWDemoMaster on whichever machine they were last edited on. They are
synced through GitHub (their own repos, not vendored into PWDemoMaster).

### Clinic source — current sync state (as of 2026-05-17)

- **Machine A** initially had the built-out Clinic source (CRUD pages
  for Clinics / Providers / Appointments + `src/lib/demoStore.ts`) but
  it was never pushed to `prime-mate-clinic`'s GitHub repo.
- **Machine B** cloned the *placeholder-stage* repo from
  https://github.com/TheJan2020/prime-mate-clinic.git, then rebuilt the
  CRUD pages + `demoStore.ts` from scratch using the recipe in §2b. The
  rebuilt source was pushed to `prime-mate-clinic`'s `origin/main`.
  The corresponding production build was copied into
  `PWDemoMaster/frontend/demos/clinic/` and committed.
- **Net result:** the canonical Clinic source now lives on **Machine
  B + GitHub**. Machine A's local working copy is stale and probably
  diverges from what's now on `origin/main`.

### Required action — Machine A owner, next session

The cleanest reconciliation is for Machine A to **discard its local
prime-mate-clinic working tree and re-clone from GitHub**, since the
Machine B rebuild is now the authoritative version:

```bash
# from the parent of the lovable-clinic / prime-mate-clinic dir
mv prime-mate-clinic prime-mate-clinic.backup-machine-a  # safety net
git clone https://github.com/TheJan2020/prime-mate-clinic.git
cd prime-mate-clinic
npm install
# verify it builds the same bundle that's already deployed:
rm -rf dist && npm run build
diff -r dist/client/ ../PWDemoMaster/frontend/demos/clinic/   # should be no diff except hashed filenames
```

If Machine A had any *additional* in-flight work in the old
`prime-mate-clinic.backup-machine-a/`, cherry-pick those files into the
fresh clone manually. Don't try to merge — the rebuild was deliberately
clean.

Then from Machine A: `cd PWDemoMaster && git pull` to pick up the new
DEMOSITEMAP and the deployed bundle.

### Rules going forward — keep both machines from drifting

1. **Always push immediately** after edits to a Lovable source repo.
   Don't accumulate uncommitted CRUD work locally; that's how this
   divergence happened in the first place.
2. **Rebuild + deploy + commit in PWDemoMaster as one atomic step**
   after every Lovable source edit:
   ```bash
   cd prime-mate-clinic
   git add -A && git commit -m "…" && git push
   rm -rf dist && npm run build
   rm -rf ../PWDemoMaster/frontend/demos/clinic/*
   cp -r dist/client/* ../PWDemoMaster/frontend/demos/clinic/
   cd ../PWDemoMaster && git add -A && git commit -m "Rebuild clinic SPA" && git push
   ```
3. **DEMOSITEMAP.md is the canonical sync log.** When sync state
   changes — when a vertical's source moves between machines, when a
   build is deployed, when a vertical's "**built**" / "placeholder"
   status flips — update §2b plus this section in the same commit.
4. **Other verticals (Restaurant, Gym, etc.):** when their Lovable
   repos are created, each one gets its own GitHub remote and its own
   sub-section here describing which machine is the source of truth.

This file is the canonical source-of-truth for the two-machine sync
state. Both machines' Claude Code sessions read it on startup.

---

## Day-to-day git workflow (multi-repo sync)

The project spans **multiple git repos** living as siblings of each
other on disk:

```
~/Documents/New Projects 2026/
├── PWDemoMaster/          ← FastAPI backend + admin app + deployed SPA bundles
│                            git remote: github.com/TheJan2020/pw-demo-master
└── prime-mate-clinic/     ← Lovable React source for the Clinic vertical
                             git remote: github.com/TheJan2020/prime-mate-clinic
```

Future verticals add more siblings (`prime-mate-restaurant/`,
`prime-mate-gym/`, etc.). All commands below assume your working
directory is the **parent folder** (`New Projects 2026/`).

### Pull every repo at once

```bash
for repo in PWDemoMaster prime-mate-clinic; do
  echo "=== $repo ==="
  (cd "$repo" && git pull --ff-only) || break
done
```

The `--ff-only` flag stops the loop if a repo has diverging commits
that need a manual merge (better than getting auto-merge commits you
didn't ask for).

### Status across every repo

```bash
for repo in PWDemoMaster prime-mate-clinic; do
  echo "=== $repo ==="
  (cd "$repo" && git status --short --branch)
done
```

### Push every repo at once

Push only sends already-committed work. Run from the parent folder
after you've staged + committed in each repo:

```bash
for repo in PWDemoMaster prime-mate-clinic; do
  echo "=== $repo ==="
  (cd "$repo" && git push)
done
```

### Full "edit Lovable source → ship" pipeline (one block, copy-paste)

Whenever you change clinic React source, this gets the change all the
way to the deployed bundle on both repos. Run from the **parent
folder**:

```bash
# 1. Commit + push the Lovable source repo
(cd prime-mate-clinic && git add -A && git commit -m "DESCRIBE THE CHANGE" && git push)

# 2. Rebuild the SPA, replace the deployed bundle in PWDemoMaster
(cd prime-mate-clinic && rm -rf dist && npm run build) \
  && rm -rf PWDemoMaster/frontend/demos/clinic/* \
  && cp -r prime-mate-clinic/dist/client/* PWDemoMaster/frontend/demos/clinic/

# 3. Commit + push PWDemoMaster
(cd PWDemoMaster && git add frontend/demos/clinic && git commit -m "Rebuild clinic SPA" && git push)
```

(Replace the commit messages with something meaningful, obviously.)

### Optional: shell function for convenience

Add to `~/.zshrc` or `~/.bashrc` for a `pw` command that operates on
every repo. Adjust the `_PW_REPOS` list when new vertical repos are
added:

```bash
_PW_REPOS=(PWDemoMaster prime-mate-clinic)
_PW_ROOT="$HOME/Documents/New Projects 2026"

pw() {
  local cmd="$1"
  case "$cmd" in
    pull|status|push|fetch)
      for r in "${_PW_REPOS[@]}"; do
        echo "=== $r ==="
        (cd "$_PW_ROOT/$r" && git "$cmd")
      done ;;
    *)
      echo "usage: pw {pull|status|push|fetch}" >&2
      return 1 ;;
  esac
}
```

After sourcing your rc file you can run `pw pull`, `pw status`,
`pw push`, `pw fetch` from anywhere.

### When you only edit backend / admin app

If your change is purely inside `PWDemoMaster/` (backend, admin
frontend, DEMOSITEMAP.md, etc.) you skip the Lovable rebuild — just
commit and push that one repo. The clinic SPA bundle isn't affected.

### After a `git pull` brings in a new clinic SPA bundle

Just restart the FastAPI backend (`./run.sh`) and hard-refresh the
browser (Cmd-Shift-R). The bundle is plain static files — no
`npm install` needed unless you'll be editing the Lovable source on
that machine yourself.

---

## 1. Verticals (initial set)

| Vertical          | URL prefix                | Demo creds         |
| ----------------- | ------------------------- | ------------------ |
| Clinic            | `/demo/clinic`            | `demo / demo`      |
| Restaurant        | `/demo/restaurant`        | `demo / demo`      |
| Gym               | `/demo/gym`               | `demo / demo`      |
| School            | `/demo/school`            | `demo / demo`      |
| Property Developer| `/demo/developer`         | `demo / demo`      |
| Gas Station       | `/demo/gas-station`       | `demo / demo`      |

Future verticals slot in as additional siblings under `/demo/<slug>`;
nothing in the architecture is per-vertical-count-dependent.

**Build order (Phase 2 → 3):** Clinic and Restaurant first
(end-to-end, client-ready), then Gym → School → Developer → Gas Station.

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

## 2b. Clinic vertical — current implementation

The Clinic demo is the reference vertical. The shape it lands in here
is what the other five should mirror once they're built.

### Stack

- **TanStack Start** (file-based router, `src/routes/`), React 19,
  Vite 7, Tailwind v4, shadcn/ui, Radix primitives, Lucide icons.
- SPA prerender mode + `cloudflare: false` (see *Design source* above).
- Source repo: `lovable-clinic/` (sibling of `pw-demo-master/`).
- Built output deployed at: `frontend/demos/clinic/`.

### Routing layout — every authenticated page is wrapped by `_app.tsx`

The file-based router uses the `_app.<segment>.tsx` convention so each
authenticated page is automatically nested inside the `_app` layout
(`src/routes/_app.tsx`). That layout provides the **sidebar**,
**topbar**, **`<Outlet/>`** content area, and an **auth guard** that
redirects to `/login` when `useApp().isAuthed` is false. Adding a new
page is just dropping a new `_app.<name>.tsx` route — no per-page
chrome wiring required.

| Page              | Route                  | File                             | State |
| ----------------- | ---------------------- | -------------------------------- | ----- |
| Login             | `/login`               | `login.tsx`                      | (no wrapper — standalone) |
| Dashboard (Home)  | `/dashboard`           | `_app.dashboard.tsx`             | static demo widgets |
| Clinics           | `/clinics`             | `_app.clinics.tsx`               | **built** — CRUD over Departments |
| Health Providers  | `/providers`           | `_app.providers.tsx`             | **built** — CRUD over Providers |
| Appointments      | `/appointments`        | `_app.appointments.tsx`          | **built** — CRUD over Appointments |
| Patients          | `/patients`            | `_app.patients.tsx`              | placeholder |
| Call Center       | `/call-center`         | `_app.call-center.tsx`           | placeholder |
| Settings          | `/settings`            | `_app.settings.tsx`              | placeholder |

### Shared demo state — `src/lib/demoStore.ts`

All CRUD pages read from the same module instead of duplicating local
`useState`. The store:

- Defines the entity **types** (`Department`, `Provider`,
  `Appointment`) and their **seed data** (`SEED_DEPARTMENTS`,
  `SEED_PROVIDERS`, `getSeedAppointments()`).
- Exposes `useDemoCollection<T>(key, seed)` — a hook that returns
  `{ items, setAll, reset }`. Seed can be a static array OR a factory
  function (Appointments uses a factory because the seed is
  date-relative).
- Persists each collection to `localStorage` under
  `pwdemo:clinic:<key>:vN` (`VERSION` bumps cycle out stale schemas).
- Dispatches a `pwdemo:clinic:data-change` window event after every
  write so any other page mounted in the same tab re-pulls — no
  Context provider needed.

### Cross-page foreign-key links

The three CRUD entities form a small relational graph:

```
Department.head_id   → Provider.id
Appointment.department_id → Department.id
Appointment.provider_id   → Provider.id
```

Linked cells render as TanStack `<Link>`s so the table reads like a
mini-CRM:

- Clinics → Head column: `<Link to="/providers" hash={head.id}>`.
- Appointments → Clinic / Provider columns: same pattern.
- The Providers page reads `useLocation().hash` on mount, scrolls the
  matching row into view, and flashes a `ring-2 ring-primary` for
  ~2 seconds. Stale FKs (deleted provider) render as
  "— unassigned —" so the page doesn't break.
- Editing the head/provider in a dialog uses a `<Select>` populated
  from the live providers collection — adding a provider on the
  Providers page makes them immediately selectable elsewhere.

### Visual conventions (use these for the other verticals)

Every CRUD page follows the same template — copy it when building the
remaining five verticals so the demos feel like one product:

1. **Heading row:** `h1` + description on the left, `Reset data` +
   `Add <entity>` buttons on the right (`<RotateCcw/>` and `<Plus/>`
   icons).
2. **Summary cards** in a `grid sm:grid-cols-2 lg:grid-cols-3-or-4`
   grid. Each card is `rounded-xl border bg-card p-5 relative` with an
   absolutely-positioned 1-px top accent bar using one of the brand
   tokens (`--brand-blue`, `--brand-purple`, `--brand-cyan`).
3. **Table card:** `rounded-xl border bg-card`. Header strip with an
   entity-tinted icon, the entity name, and a "{filtered} of {total}"
   counter. Filter widgets (if any) live in the right side of the
   header strip.
4. **Edit/Add dialog** via shadcn `Dialog` (`sm:max-w-lg`) with a
   `grid grid-cols-2 gap-3` body; ID input is disabled when editing.
5. **Delete confirmation** via shadcn `AlertDialog` with the
   destructive-tinted action button. **Reset** also uses an
   `AlertDialog` so accidental clicks don't wipe local edits.
6. **Status pills** are `inline-flex rounded-full px-2 py-0.5 text-xs
   font-medium` with status-specific tints (emerald / amber / sky /
   muted).

### Appointments — date-relative seed (Reset always centres on today)

`getSeedAppointments()` returns a fresh window from `today − 20` to
`today + 10` (31 days, today inclusive) on every call. Each day is
seeded with a deterministic per-day RNG (Mulberry32 keyed by
`YYYY-MM-DD`) so the rows stay stable within a day, but the window
slides with `new Date()` so a Reset tomorrow gives a fresh ±20/+10
around the new "today". Past days lean `completed` with some
`cancelled` / `no_show`; today is split by clock time; the future is
all `scheduled`.

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
| Clinic            | Today's appointments, patient queue, prescriptions, follow-up calls due          |
| Restaurant        | Today's reservations, table availability, kitchen orders, top-selling items      |
| Gym               | Members, today's classes, trial-pass requests, monthly check-ins                 |
| School            | Students, attendance, parent inquiries, fee status                               |
| Property Developer| Leads pipeline, available units, scheduled viewings, sales funnel                |
| Gas Station       | Today's volume, pump status, loyalty members, fleet account inquiries, complaints |

Info-collection schema (Live Rep) per vertical — examples:

- **Clinic:** patient name, phone, symptom summary, preferred doctor.
- **Restaurant:** name, party size, date/time, dietary notes.
- **Gym:** name, phone, fitness goal, preferred trial date.
- **School:** parent name, child name, grade level, contact, inquiry topic.
- **Property Developer:** name, contact, budget range, unit type interest.
- **Gas Station:** name, contact, vehicle / fleet info, fuel type interest, loyalty card status.

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
    clinic/
      __init__.py
      router.py             # all clinic endpoints under /api/demo/clinic/*
      config.py             # persona, KB, info_schema, brand, creds
      seed.json             # initial dummy data
    restaurant/   ... same shape
    gym/          ... same shape
    school/       ... same shape
    developer/    ... same shape
    gas_station/  ... same shape   (folder name uses underscore; URL slug "gas-station")
```

### Frontend

```
frontend/demos/
  index.html                # /demo landing page (6 cards)
  styles.css                # landing-only styles
  clinic/                   # TanStack Start build output
    index.html              # prerendered SPA shell w/ hydration markers
    assets/
      <hash>.js, <hash>.css, <hash>.png …
  restaurant/   ... built from its own Lovable repo, same shape
  gym/          ... same shape
  school/       ... same shape
  developer/    ... same shape
  gas-station/  ... same shape
```

The Lovable source repos live as siblings of `pw-demo-master/`
(`lovable-clinic/`, `lovable-restaurant/`, …) and are **not** vendored
into this repo. Only the build output is checked in under
`frontend/demos/<slug>/`.

### Data

```
data/
  demos/
    clinic.json
    restaurant.json
    gym.json
    school.json
    developer.json
    gas_station.json
```

`data/demos/` is gitignored along with the existing `data/` rule.
`seed.json` (checked in, inside each vertical's backend folder) is the
template; first request creates the live data file from it.

---

## 5. Phased plan

Each phase ships a demo that you can show to a client by itself.

### Phase 0 — decisions (no code)

- Lock the Live Rep wiring model (single UUID-routed port vs. six
  ports). Default to **UUID-routed single port** unless we hit a
  blocker.
- **First two verticals to build end-to-end: Clinic and Restaurant**
  (locked).
- Designs authored in **Lovable**, exported to GitHub. We translate them
  to vanilla HTML/CSS/JS for ingestion into this repo. Lovable export =
  design reference, not deployed source.

### Phase 1 — Foundations (~1 day)

- `backend/app/demos/` package skeleton.
- `auth.py` — session cookie middleware (signed cookie, scoped path).
- `common/db.py` — load/save JSON with the seed-on-first-run pattern.
- `landing.py` — `/demo` 6-card page listing the verticals.
- Each vertical's `router.py` registered but only exposing `/login`,
  `/me`, `/logout`. Dashboard returns "Coming soon" placeholder.
- Each vertical's `index.html` + minimal themed shell (no widgets yet).
- Wire `backend/app/main.py` to mount the demos router + static files.
- Hardcoded creds work, session round-trip works, dashboard renders
  with a "Welcome, demo" greeting.

**Deliverable:** all six logins work, all six dashboards open empty
with their own colors / fonts / logo.

### Phase 2 — Clinic + Restaurant, end-to-end (~2–3 days each)

Build the first two verticals to client-ready quality. **Clinic
first, then Restaurant** — both share the same scope:

- Dashboard widgets driven by `data/demos/<vertical>.json`.
- Mini-CRM for that vertical's entities (patients / reservations).
- Settings page wired to `config.py` (persona / KB / info-schema /
  brand / creds editable from the UI, persisted to the JSON DB).
- Live Rep page scoped to this vertical's persona / KB / schema.
  Reuses the existing AudioSocket service but reads vertical-specific
  config based on the call's UUID prefix.
- Vertical-specific call-history view that pulls into the dashboard.

**Deliverable:** Clinic and Restaurant demos are both client-ready.
Login → branded dashboard → live phone call into Lena (now a
clinic receptionist / restaurant host persona) → collected info shows
up on the dashboard.

**Clinic status (current):** the chrome (login + auth-guarded `_app`
layout + sidebar + topbar + dashboard) and three CRUD pages —
**Clinics, Health Providers, Appointments** — are built and FK-linked
through `src/lib/demoStore.ts` (see §2b for the full breakdown).
Mutations persist to `localStorage`, not yet to the JSON DB on the
backend. **Remaining for client-ready:** wire the three CRUD pages to
`/api/demo/clinic/*` so edits hit `data/demos/clinic.json`; build
Patients, Call Center, and Settings (currently placeholders); scope
the Live Rep persona / KB / info-schema to the clinic; surface live
call info on the Dashboard.

### Phase 3 — Clone to the remaining four verticals (~1 day each)

For each of Gym, School, Developer, Gas Station:

- Duplicate one of the Phase-2 vertical folders as the starting point.
- Swap brand colors, logo, fonts.
- Customize widget set for that vertical.
- Customize seed data (sample patients → sample members, etc.).
- Customize Live Rep persona, KB, info-schema.
- Hook up the dialplan extension and UUID prefix.

**Deliverable:** all six vertical demos client-ready and
distinguishable.

### Phase 4 — Polish (~1 day)

- Landing page redesign — visual mini-portfolio of the six demos with
  short pitches, screenshots, "Try it" buttons.
- README section explaining how to demo each vertical (which extension
  to dial, what credentials to use, what to look for on the dashboard).
- One-pager PDF / handout (optional — for client meetings).

---

## 6. Live Rep wiring — UUID-routed single port (preferred)

### How a call flows end-to-end

1. Client dials extension on FreePBX (one per vertical):
   - `9991` → Clinic
   - `9992` → Restaurant
   - `9993` → Gym
   - `9994` → School
   - `9995` → Developer
   - `9996` → Gas Station
2. Dialplan for each extension sets a vertical-prefixed UUID and calls
   the same AudioSocket port:

   ```ini
   [pwdemo-clinic]
   exten => s,1,NoOp(Clinic demo)
    same => n,Answer()
    same => n,Set(AUDIOSOCKET_UUID=clinic-demo-00000000-0000-0000-0000-000000000001)
    same => n,AudioSocket(${AUDIOSOCKET_UUID},192.168.100.89:8091)
    same => n,Hangup()
   ```
3. Backend `sip_live_rep.py` reads the UUID's prefix (`clinic-demo-...`),
   looks up `backend/app/demos/clinic/config.py`, and opens the Gemini
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

### Fallback: six separate ports

If UUID routing becomes a problem (it shouldn't), run six `Service`
instances on ports 8091–8096, each with a hardcoded vertical. Dialplan
points each extension at its dedicated port. Simpler but uses 6× the
memory and 6× the lifecycle bookkeeping.

---

## 7. Open decisions to lock before Phase 1

1. **First two verticals to build end-to-end** — ✅ **Clinic + Restaurant** (locked).
2. **Lovable design ingestion path** — ✅ **Ship the React build as-is**
   (locked). One-time `npm run build` per design update; `dist/`
   becomes `frontend/demos/<slug>/`. FastAPI serves the static files.
3. **Brand assets** — full design pass per vertical from Lovable, or
   simple color-swap-and-text-logo for the early demos?
4. **PBX extension numbers** — confirm `9991–9996` are free on the
   demo FreePBX, or pick alternatives.
5. **Dashboard density** — minimal (3 widgets) or full (8+) per
   vertical? Affects Phase 2 / 3 effort estimates.
6. **Editable settings per vertical** — should the persona/KB be
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
