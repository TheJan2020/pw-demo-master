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

### Clinic source — current sync state (as of 2026-05-17, end-of-day)

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

#### Switching to Machine A (Windows) — what to pull, and what's new

Both repos are fully pushed to `origin/main`. Pick **one** of the
two shells below — Git Bash is preferred because every other
snippet in this file works verbatim there.

**Option A — Git Bash (recommended)**

Git Bash ships with Git for Windows. Open it (Start menu → "Git
Bash") and run the same commands the macOS machine uses:

```bash
export PW_ROOT="/c/Users/$USER/Documents/New Projects 2026"
for repo in PWDemoMaster prime-mate-clinic; do
  echo "=== $repo ===" && (cd "$PW_ROOT/$repo" && git pull --ff-only)
done

# Verify clean:
for repo in PWDemoMaster prime-mate-clinic; do
  echo "=== $repo ===" && (cd "$PW_ROOT/$repo" && git status --short --branch)
done
```

If the projects live somewhere other than `Documents/New Projects
2026`, just adjust `PW_ROOT` — Git Bash accepts both `/c/Users/…`
and `C:/Users/…` style paths.

**Option B — PowerShell**

```powershell
$env:PW_ROOT = "$env:USERPROFILE\Documents\New Projects 2026"
foreach ($repo in "PWDemoMaster", "prime-mate-clinic") {
  Write-Host "=== $repo ==="
  Push-Location "$env:PW_ROOT\$repo"
  git pull --ff-only
  Pop-Location
}

# Verify clean:
foreach ($repo in "PWDemoMaster", "prime-mate-clinic") {
  Write-Host "=== $repo ==="
  Push-Location "$env:PW_ROOT\$repo"
  git status --short --branch
  Pop-Location
}
```

**Windows-only path notes for the rest of this file:**

- The Python venv interpreter on Windows is
  `.venv\Scripts\python.exe` (PowerShell) or
  `.venv/Scripts/python.exe` (Git Bash), NOT `.venv/bin/python`.
  Activate with `.venv\Scripts\Activate.ps1` (PowerShell) or
  `source .venv/Scripts/activate` (Git Bash).
- `npm run build` works identically on either shell.
- All `git`, `npm`, `node` commands work identically on either shell.
- The "edit Lovable source → ship" copy step uses `cp -r` on macOS;
  Git Bash also has `cp -r`. In PowerShell use
  `Copy-Item -Recurse -Force` instead, and
  `Remove-Item -Recurse -Force` instead of `rm -rf`.

Recent work since the last machine-A session, in rough order of how
it affects what you'll see on screen:

**Clinic Live Agent — backend (`PWDemoMaster`):**

- `c40e93b` Fabrication detector now treats bare `HH:MM` (no AM/PM)
  as ambiguous and checks both AM and +12 interpretations. Closes
  the false-positive that was telling the agent to apologise for
  successful 4:30 PM reschedules.
- `4e4cef8` Three new tools: `list_patient_appointments`,
  `cancel_appointment`, `reschedule_appointment`. Plus a
  slot-time fabrication check so the agent can't quote off-hours
  slots like "6:30 PM" that `list_free_slots` never returned.
- `9007d09` Real-time fabrication detector + in-session correction.
  CallSession tracks every `file_number` / `appointment_id` /
  `patient_id` returned by a successful tool call; if the agent
  SPEAKS one that isn't in the whitelist, the backend injects a
  system-override correction back into the live Gemini session AND
  broadcasts a `fabrication` WS event for the Dashboard's red panel.
- `8a3340f` `create_patient` now only requires `name`. Plus a
  GUARDRAIL block listing the six questions the agent MUST ASK
  (especially the national ID, which had been getting skipped).
- `55654e8` Broadcasts a `tool_result` event on every tool call
  outcome — drives the new "Recent tool errors" panel on the
  Dashboard so silent failures stop being silent.
- `7279e75` Fixed call sessions hanging after Asterisk drops TCP —
  `_write_loop` / `_read_loop` / `feed` / `receive` all now signal
  `stop_evt` in a `finally` so `CallSession.run()` always finalises.
- `7ead997` Always-on `_GUARDRAILS` block + per-call roster
  injection (snapshot's clinics + providers go into every system
  instruction). Anti-fabrication and patient-privacy rules are now
  structural and can't be bypassed by editing the persona text.
- `6f95312` `mixed.wav` (caller+agent overlay) + Gemini offline
  transcript enhancement. History page shows a "Full call" player
  and prefers the cleaned transcript when present.

**Clinic Live Agent — frontend (`prime-mate-clinic`):**

- `91f7303` Agent mutation drain lifted from Dashboard to `_app.tsx`
  layout. Cancellations / reschedules / creations the agent does
  now apply to localStorage regardless of which page the user is
  viewing during a call, and the backend's `snapshot.json` can no
  longer be overwritten with stale SPA state.
- `d6f5e47` Dashboard activity feed handles the new
  `appointment_cancelled` / `appointment_rescheduled` mutations
  (reschedule shows old → new time).
- `0fdec9f` New red Dashboard panel for fabricated identifiers.
- `18f7e26` New red Dashboard panel for tool errors.
- `f88459d` Live transcript no longer wiped on WS reconnect
  (snapshot now merges instead of replacing).
- `22ddf5b` History page shows the new "Full call" audio player and
  the enhanced offline transcript with status banner.

After the pull, the bundle under `frontend/demos/clinic/` already
matches the latest `prime-mate-clinic/src` — no rebuild needed for
just reading or running. If you EDIT clinic React code on Machine
A, run the standard pipeline from §"Full edit → ship" below.

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
`prime-mate-gym/`, etc.).

All snippets below use an absolute `PW_ROOT` variable so they work
**from any working directory** — including from inside one of the
repos. Set it once per shell (or add to `~/.zshrc`):

```bash
export PW_ROOT="$HOME/Documents/New Projects 2026"
```

### Pull every repo at once

```bash
for repo in PWDemoMaster prime-mate-clinic; do
  echo "=== $repo ==="
  (cd "$PW_ROOT/$repo" && git pull --ff-only) || break
done
```

The `--ff-only` flag stops the loop if a repo has diverging commits
that need a manual merge (better than getting auto-merge commits you
didn't ask for).

### Status across every repo

```bash
for repo in PWDemoMaster prime-mate-clinic; do
  echo "=== $repo ==="
  (cd "$PW_ROOT/$repo" && git status --short --branch)
done
```

### Push every repo at once

Push only sends already-committed work. Run after you've staged +
committed in each repo:

```bash
for repo in PWDemoMaster prime-mate-clinic; do
  echo "=== $repo ==="
  (cd "$PW_ROOT/$repo" && git push)
done
```

### Full "edit Lovable source → ship" pipeline (one block, copy-paste)

Whenever you change clinic React source, this gets the change all the
way to the deployed bundle on both repos. Works from any directory
(uses the absolute `PW_ROOT` from above):

```bash
# 1. Commit + push the Lovable source repo
(cd "$PW_ROOT/prime-mate-clinic" && git add -A && git commit -m "DESCRIBE THE CHANGE" && git push)

# 2. Rebuild the SPA, replace the deployed bundle in PWDemoMaster
(cd "$PW_ROOT/prime-mate-clinic" && rm -rf dist && npm run build) \
  && rm -rf "$PW_ROOT/PWDemoMaster/frontend/demos/clinic/"* \
  && cp -r "$PW_ROOT/prime-mate-clinic/dist/client/"* "$PW_ROOT/PWDemoMaster/frontend/demos/clinic/"

# 3. Commit + push PWDemoMaster
(cd "$PW_ROOT/PWDemoMaster" && git add frontend/demos/clinic && git commit -m "Rebuild clinic SPA" && git push)
```

(Replace the commit messages with something meaningful, obviously.)

### Optional: shell function for convenience

Add to `~/.zshrc` or `~/.bashrc` for a `pw` command that operates on
every repo. Adjust the `_PW_REPOS` list when new vertical repos are
added:

```bash
export PW_ROOT="$HOME/Documents/New Projects 2026"
_PW_REPOS=(PWDemoMaster prime-mate-clinic)

pw() {
  local cmd="$1"
  case "$cmd" in
    pull|status|push|fetch)
      for r in "${_PW_REPOS[@]}"; do
        echo "=== $r ==="
        (cd "$PW_ROOT/$r" && git "$cmd")
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

## 6b. Clinic Live Agent — IMPLEMENTED (per-vertical port, the fallback model)

We went with the **per-vertical-port fallback** for the Clinic demo —
not UUID multiplexing — because it isolates the demo from the admin
SLA / SLR services and lets a single FreePBX install grow one
vertical at a time without touching shared code.

### Port allocation (locked)

| Service                                 | Port  | State namespace |
| --------------------------------------- | ----- | --------------- |
| Admin Live Assistant (SLA)              | 8090  | `sla_*`         |
| Admin Live Representative (SLR / Lena)  | 8091  | `slr_*`         |
| **Clinic Demo Live Agent (Layla)**      | **8092** | **`cda_*`**  |
| Restaurant Demo Live Agent (future)     | 8093  | `rda_*`         |
| Gym / School / Developer / Gas Station  | 8094–8097 | …          |

8090 and 8091 are reserved for the PWDemoMaster admin app — the
clinic demo and every future vertical demo claims the next free port
above them.

### Code map

- `backend/app/demos/clinic/live_agent.py`
  - `ClinicLiveAgentService` — TCP listener + per-call dispatch +
    pub/sub bus for the Dashboard WebSocket.
  - `CallSession` — AudioSocket framing, audio resample, Gemini Live
    session, transcription forwarding, deadline-killer.
  - `load_persona() / load_kb() / save_persona() / save_kb()` —
    on-disk overrides at `data/demos/clinic/persona.txt` and
    `…/kb.txt`. Default seeds in the same module (kept in sync with
    the Clinic SPA's `clinicLiveData.ts` seeds).
- `backend/app/demos/clinic/router.py` — REST surface:
  - `GET/POST /api/demo/clinic/agent/config`  — toggle, host, port,
    voice, greeting, max_call_s, interruption_enabled.
  - `GET /api/demo/clinic/agent/status` — service running flag, host
    + port, list of active calls, persona/KB char counts, gemini-key
    flag.
  - `GET/POST /api/demo/clinic/agent/prompt` — read / write the
    persona + KB texts.
  - `WS /api/demo/clinic/agent/ws` — push `call_started` /
    `call_ended` / `transcript` events for the Dashboard.
- `backend/app/core/state.py` — `cda_*` fields (enabled, bind_host,
  bind_port = 8092, voice = "Aoede", greeting (Arabic), max_call_s,
  interruption_enabled). Persisted to `data/state.json`.
- `backend/app/main.py` — `clinic_live_agent_service.apply_config()`
  at lifespan startup; `.stop()` at shutdown.

### Frontend wiring

The Clinic SPA's Knowledge Base + Persona pages each gain an
**"Apply to Live Agent"** button (`src/components/PromptEditor.tsx`).
Clicking it POSTs the saved body to `/api/demo/clinic/agent/prompt`,
which writes the file. The service rereads from disk on every
inbound call so no restart is needed to roll out an updated prompt.

The button is disabled while the editor has unsaved changes — Save
first, then Apply.

### FreePBX dialplan (Clinic — extension 9001)

Add to `/etc/asterisk/extensions_custom.conf` on the FreePBX box:

```ini
[pwdemo-clinic-agent]
exten => s,1,NoOp(Clinic Live Agent — Layla)
 same => n,Answer()
 same => n,Wait(0.3)
 same => n,Set(AUDIOSOCKET_UUID=33333333-3333-3333-3333-333333333333)
 same => n,AudioSocket(${AUDIOSOCKET_UUID},192.168.100.89:8092)
 same => n,Hangup()
```

**Two non-obvious things this dialplan gets right:**

1. **The UUID must be a real 36-char UUID** (`8-4-4-4-12` hex with
   dashes). `app_audiosocket` validates the format and silently
   hangs up the call if it's anything else. With the per-vertical-port
   model the UUID is just an opaque per-call id — pick any valid
   value (we use repeated digits so they're easy to recognise in
   the AudioSocket service logs: `1111-…` = admin SLA, `2222-…`
   = admin SLR, `3333-…` = Clinic).
2. **`Wait(0.3)` between `Answer()` and `AudioSocket(...)`** —
   without it Asterisk's RTP isn't primed when the TCP connection
   opens and the first 200–300 ms of audio drops, sometimes causing
   the call to disconnect.

(Replace `192.168.100.89` with the IP of the machine running
PWDemoMaster.)

Then in the FreePBX UI:

1. **Admin → Custom Destinations** → add target
   `pwdemo-clinic-agent,s,1`, description `Clinic Live Agent`.
2. **Applications → Misc Applications** → add feature code `9001`,
   destination = the Custom Destination above.
3. Submit + Apply Config.
4. SSH the FreePBX box and reload Asterisk:

   ```bash
   /usr/sbin/asterisk -rx "module reload chan_audiosocket app_audiosocket"
   /usr/sbin/asterisk -rx "dialplan reload"
   ```

5. From any registered SIP extension, dial `9001`. The call lands
   on AudioSocket port 8092, the backend opens a Gemini Live
   session with the current clinic persona + KB, and Layla picks up
   with the Arabic greeting.

### Backend deploy steps (one-time per machine)

```bash
# 1. Pull the latest backend code
cd "$PW_ROOT/PWDemoMaster"
git pull --ff-only

# 2. (no new Python deps were added — same .venv)
# 3. Make sure the data dir exists for prompt overrides
mkdir -p data/demos/clinic

# 4. Enable the agent in state.json (or via the UI):
curl -s -X POST http://localhost:8080/api/demo/clinic/agent/config \
  -H "content-type: application/json" \
  -d '{"enabled": true, "bind_port": 8092}'

# 5. Restart the FastAPI backend so the lifespan picks up the new
#    service (./run.sh, or whatever wrapper you use).
# 6. Sanity-check the listener is up:
lsof -nP -iTCP:8092 -sTCP:LISTEN     # macOS / BSD
# or: ss -lntp | grep 8092            # Linux
```

### Call recording + History (IMPLEMENTED)

Every call is now persisted to disk when it hangs up, and surfaced
on a new `/call-center/history` page:

- **Storage layout**: `data/demos/clinic/calls/<id>/`
  where `<id>` = `YYYYMMDDTHHMMSS_<call_id>` (sortable timestamp +
  short uid). Three files per directory:
    - `caller.wav` — 8 kHz signed-linear mono, what the caller said
      (captured straight from the AudioSocket frames before any
      resampling, so it's lossless).
    - `agent.wav` — 8 kHz signed-linear mono, what the agent said
      *as the caller heard it* (captured after the 24 → 8 kHz
      downsample, immediately before the AudioSocket send).
    - `meta.json` — `{id, call_id, started_at, ended_at, duration_s,
      peer, uuid, caller_phone, turns[], voice, persona_chars,
      kb_chars}`. `turns[]` is the in-call transcript as a list of
      `{role: "caller"|"agent", text, ts}`, role-collapsed so multi-
      chunk transcript fragments come out as one turn.
- **Endpoints** (router.py):
    - `GET /api/demo/clinic/agent/calls?limit=100` — list summaries.
    - `GET /api/demo/clinic/agent/calls/{id}` — full meta + turns.
    - `GET /api/demo/clinic/agent/calls/{id}/audio/{caller|agent}`
      — streams the WAV.
    - `DELETE /api/demo/clinic/agent/calls/{id}` — removes the
      entire directory.
- **Dashboard ↔ WS hookup**: the Clinic SPA's Call Center →
  Dashboard now subscribes to `/api/demo/clinic/agent/ws`. Active
  calls + the live transcript stream are real-time. New calls
  default to `caller_name = "New patient"` until a lookup tool
  resolves them (see deferred work below).
- **History page**: lists calls newest-first, expand a row to play
  the caller + agent WAVs (HTML5 `<audio controls>`) and read the
  full transcript. Per-row Delete wipes the directory after a
  confirm dialog.
- **Patient `id_number`**: the Patient schema gained a national /
  Iqama ID field, 10 digits — `1xxxxxxxxx` Saudi national,
  `2xxxxxxxxx` resident. Seeded with the ~80/20 split that matches
  the typical clinic mix. Visible in the Patients table and
  validated in the edit dialog. The Live Agent's intake flow now
  asks for this when verifying a returning caller.

### Function-call tools (IMPLEMENTED — Option B, SPA pushes snapshot)

We went with **Option B** from the original three-way fork: the SPA
remains the source of truth, but its Dashboard pushes a snapshot to
the backend on every relevant mutation, and the agent's tools read
(and mutate) that snapshot.

**Tools** (`backend/app/demos/clinic/agent_tools.py`, declared via
`build_tools()` and dispatched via `execute_tool(name, args, ctx)`):

| Tool                              | What it does                                                                 |
| --------------------------------- | ----------------------------------------------------------------------------- |
| `lookup_patient_by_phone(phone)`  | Loose match — strips formatting + accepts ±966/0 prefix. Returns full patient |
| `lookup_patient_by_id_number(id)` | Match against the 10-digit national/Iqama ID                                  |
| `lookup_patient_by_file_number(f)`| Match against `A/B/C + 6 digits` clinic file #                                |
| `list_free_slots(date, clinic_id?)` | Returns 'HH:MM' slot list per clinic. **Filters past times and the 15-min booking buffer for today.** |
| `create_patient(...)`             | Creates a new Patient + assigns next file_number; broadcasts `tool_mutation` |
| `create_appointment(...)`         | Books a slot after re-verifying free + non-break + within hours + outside buffer |
| `end_call(reason)`                | Sets `end_requested` — receive loop schedules a 3 s delayed `stop_evt` so the agent's spoken goodbye lands before the AudioSocket closes |

**Sync model — three flows**:

1. **SPA → backend (snapshot push):** the Clinic SPA's Dashboard
   useEffect POSTs the full `{patients, appointments, clinics,
   providers, slot_overrides}` to `POST /api/demo/clinic/data/snapshot`
   on mount and on any change to the local collections it reads.
   Backend stores at `data/demos/clinic/snapshot.json`. The agent's
   tools `load_snapshot()` from this file on every call.
2. **Backend → SPA (tool_mutation events):** after a `create_patient`
   or `create_appointment` tool succeeds, the backend broadcasts a
   `tool_mutation` event over `/api/demo/clinic/agent/ws` containing
   the new record. The SPA's `liveAgentStore` collects them; the
   Dashboard's useEffect drains the buffer, mirrors the record into
   the SPA's localStorage (so the Patients / Appointments / Calendar
   pages show what the agent did), AND adds a matching row to the
   existing agent_activity collection so per-row Delete-with-cascade
   keeps working.
3. **Caller identification:** after any `lookup_patient_by_*` returns
   a match, the backend broadcasts a `caller_identified` event with
   the resolved name + phone. The Dashboard's singleton WS store
   updates the active call's `caller_name` and `caller_phone` so the
   ActiveCallCard switches from "New patient" to the real name in
   real time.

**Time awareness:**
`_build_system_instruction()` (in `live_agent.py`) appends a
`## CURRENT TIME (authoritative …)` block to every system prompt
with the local date, weekday in English + Arabic, and "Right now: HH:MM
TZ". The persona instructs the agent never to invent a weekday and
to trust `list_free_slots` for the past-time / 15-min-buffer filtering
(matching what the tool actually enforces).

**End-of-call behaviour:**
Persona now explicitly says: "When the caller says bye, summarise →
say the closing line → IMMEDIATELY call `end_call`." On `end_call`,
`tool_ctx["end_requested"]` flips True, the receive loop schedules a
3-second `asyncio.sleep` then sets `stop_evt`, giving the agent's
goodbye audio time to leave the wire before the TCP/AudioSocket teardown.

**Transcript persistence across SPA navigation:**
`src/lib/liveAgentStore.ts` owns the WebSocket connection as a
module-level singleton. Components subscribe via `useLiveAgentStore()`.
Navigating between Dashboard / Patients / Configuration etc. no
longer tears down the connection or wipes the in-flight transcript —
state survives until the call ends (or the browser does a full reload).

### Open follow-ups (not in §6b)
- **SIP CALLERID → AudioSocket UUID**: the agent doesn't currently
  receive the caller's phone number — `chan_audiosocket` only
  carries audio + a UUID. To enable `lookup_patient_by_phone` we
  need to either:
    - Encode the CALLERID in the UUID (set via dialplan from
      `${CALLERID(num)}`, then the service splits on a delimiter),
      OR
    - Push CALLERID over a separate channel (AMI / ARI / a small
      HTTP webhook from the dialplan to the backend) keyed by call
      UUID.
  Either is straightforward Asterisk dialplan work + a 20-line
  backend lookup table.
- **Activity feed real-event sync**: the Clinic SPA's Dashboard
  activity feed is currently driven by the Simulate buttons. Once
  the function tools land, real `create_patient` /
  `create_appointment` / `cancel_appointment` / `reschedule_*` calls
  from the agent should publish into the same `agent_activity`
  collection (via `/api/demo/clinic/agent/ws` events that include
  the patient_id / appointment_id) so they show up live and remain
  cascade-deletable from the dashboard.

---

## 6c. Clinic Live Agent — supervisor escalation + dial-in (IMPLEMENTED)

End-to-end "the agent flags a call, a human supervisor joins via AMI"
feature. The dial-in supports three modes: **Listen** (silent monitor),
**Whisper** (talk to the caller only), **Barge** (3-way — caller and
agent both hear the supervisor). Built on top of §6b.

### What the operator experiences

1. On the **Dashboard** (`/demo/clinic/call-center/dashboard`), every
   active call row has a 3-button group: `[👂 Listen | 💬 Whisper | 📣 Barge]`.
   They sit in the Status column next to the duration counter.
2. The agent can flag a call when the caller is angry, asks for a
   manager, or the agent is stuck. Flagged rows paint **red** with a
   banner showing the reason, plus the same 3-button group + an
   **Acknowledge** button that clears the flag.
3. Click any of the 3 buttons → backend issues an AMI Originate →
   supervisor's phone rings → on answer they're in the live call with
   the chosen audio policy.
4. If AMI isn't reachable / creds are wrong, the button falls back to
   **copy-to-clipboard** and surfaces the error in its tooltip — so the
   demo never gets stuck.

### Backend pieces

| File | Purpose |
| --- | --- |
| `backend/app/demos/clinic/live_agent.py` | `DEFAULT_ESCALATION` constant + `load_escalation_config()` / `save_escalation_config()` for the operator-editable config persisted at `data/demos/clinic/escalation.json`. `CallSession.set_flag()` / `ack_flag()` + `active_flag` field. `_build_system_instruction()` injects the **ESCALATION** block (operator-saved keywords + scenarios) into every per-call prompt. |
| `backend/app/demos/clinic/agent_tools.py` | `flag_for_supervisor(reason, severity)` function tool declaration + dispatch + `_t_flag_for_supervisor` handler. The handler calls `ctx["set_flag"](…)` which CallSession exposed. |
| `backend/app/demos/clinic/ami.py` | **NEW.** Minimal pure-asyncio AMI client (no `panoramisk` dep). `AMICredentials` dataclass + `AMIClient.originate()` + `AMIClient.core_show_channels()` + `AMIService.dial_supervisor(call_id, ext, spy_mode)` which: (1) finds the channel running the AudioSocket application via `CoreShowChannels`, (2) originates `Local/{ext}@from-internal/n` with `Application: ChanSpy, Data: <target>,<opts>`, (3) falls back to ring+`Playback,beep` if no AudioSocket channel found. |
| `backend/app/demos/clinic/router.py` | New endpoints: **`GET/POST /api/demo/clinic/agent/escalation`** (config read/write — partial PATCH allowed), **`POST /api/demo/clinic/agent/calls/{call_id}/acknowledge_flag`**, **`POST /api/demo/clinic/agent/calls/{call_id}/dial_supervisor?mode={listen,whisper,barge}`**. |

WebSocket events on `/api/demo/clinic/agent/ws`:
- `supervisor_flag` — `{call_id, flag: {reason, severity, source, ts}}`. Emitted by `CallSession.set_flag`.
- `supervisor_flag_ack` — `{call_id}`. Emitted by `CallSession.ack_flag`.
- Snapshot replay (sent on every connect) includes per-call `flag` so dashboards that come online AFTER a flag was raised still see the red row.

### Frontend pieces

| File | Purpose |
| --- | --- |
| `src/lib/liveAgentStore.ts` | New `SupervisorFlag` type + `supervisorFlags: Record<call_id, SupervisorFlag>` in store state. Handlers for `supervisor_flag` / `supervisor_flag_ack`. Exported `acknowledgeFlag(callId)` — optimistic remove + POST, restores on failure. `call_ended` cleans up any leftover flag. |
| `src/routes/_app.call-center.dashboard.tsx` | Three new components: `LiveCallsTable` (replaced the old 2-card layout with a unified multi-call table; yellow/green/red tinting; click-to-expand inline transcript drawer), `FlagBanner` (red strip with reason + Ack + dial buttons), `DialModeButtons` / `DialModeOne` (the 3-button group with state machine: idle → calling → ringing → idle; copy-to-clipboard fallback on AMI error). Also `looksLikeGarbage(text)` — frontend filter that hides Gemini mis-transcriptions (CJK / Cyrillic / Greek in a Saudi-Arabic call) with an `[unintelligible audio]` placeholder. |
| `src/routes/_app.call-center.configuration.tsx` | New self-contained `EscalationConfigCard` at the bottom of the Configuration page. Edits `escalation.json` via the GET/POST endpoint. Sections: **Supervisor extension** → **PBX integration (AMI)** subsection (host / port / username / secret) → **Keyword examples** EN/AR (illustrative, not exact-match triggers) → **Scenarios** (free-text rules the agent reads) → **Auto-detect** toggles (placeholders; auto-detect code itself is a future increment). |

### Storage — `data/demos/clinic/escalation.json` (gitignored)

```jsonc
{
  "keywords_en": ["manager", "supervisor", "speak to a human", ...],
  "keywords_ar": ["مدير", "مديرة", "اريد بشر", ...],
  "scenarios":   ["The caller has raised their voice...", ...],
  "supervisor_extension": "1003",       // PBX ext that gets dialed
  "ami_host":             "192.168.100.23",
  "ami_port":             5038,
  "ami_username":         "pwdemo-clinic",
  "ami_secret":           "<40-char hex>",
  "auto_keyword_match":   true,         // toggle reserved for future code
  "auto_on_tool_errors":  true,         // ditto
  "tool_error_threshold": 3
}
```

This file is **per-machine**. Re-enter the AMI host / username / secret
on each machine via the Configuration page — `data/` is gitignored, the
secret never travels through git.

### Per-machine setup checklist — FreePBX (one-time per PBX)

The PBX-side bits aren't in our repo. Do them once per FreePBX
deployment:

**1. Asterisk Manager Interface (AMI) — bind address**

By default FreePBX 16+ binds AMI to `127.0.0.1` only. Our backend lives
on a different host, so this must change:

- FreePBX UI: **Settings → Advanced Settings** → flip *"Display Readonly Settings"* + *"Override Readonly Settings"* to **Yes** → search `AMI` → set **AMI bind address** to `0.0.0.0` → **Submit** → red **Apply Config** bar.
- Or SSH: edit `/etc/asterisk/manager.conf`, set `bindaddr = 0.0.0.0` in `[general]`, then `/usr/sbin/asterisk -rx "manager reload"`.

Verify from the backend host: `Test-NetConnection <pbx-ip> -Port 5038`
should return `TcpTestSucceeded : True`.

**2. Manager user**

- FreePBX UI: **Admin → Asterisk Manager Users → Add Manager**
- **User Name:** `pwdemo-clinic`
- **Secret:** strong (40+ char hex/base64)
- **Deny:** `0.0.0.0/0.0.0.0`
- **Permit:** the BACKEND's IP — e.g. `192.168.100.25/255.255.255.255`, OR the whole LAN `192.168.100.0/255.255.255.0`. ⚠️ **Gotcha:** `0.0.0.0/255.255.255.0` does NOT mean "everyone" — it means "the 0.0.0.0/24 network". Use the actual subnet.
- **Read:** check `system, call, log, verbose, agent, user, config, command, dtmf, reporting, cdr, dialplan, originate, message`
- **Write:** same set (originate is the strictly-required one for this feature)
- **Submit → Apply Config**

Verify auth: on the backend host run
```bash
echo -e "Action: Login\r\nUsername: pwdemo-clinic\r\nSecret: <secret>\r\n\r\nAction: Logoff\r\n\r\n" | nc <pbx-ip> 5038
```
You want `Response: Success`. If you get `Authentication failed` while
the secret is right, almost always the Permit IP doesn't include the
backend (check `/var/log/asterisk/full` for an `ACL` rejection line).

**3. Dialplan — Local-pair wrap for ChanSpy**

`AudioSocket()` run directly on the caller's channel works fine for the
agent itself, BUT `ChanSpy` won't capture the write side (Gemini's
voice) because AudioSocket doesn't expose those frames via the
audiohook framework. Workaround: bridge the caller to a Local channel
that runs AudioSocket in its other leg — then it's a normal bridge
ChanSpy understands.

Edit `/etc/asterisk/extensions_custom.conf`:

```ini
[pwdemo-clinic-agent]
exten => s,1,NoOp(Clinic Live Agent — Layla)
 same => n,Answer()
 same => n,Wait(0.3)
 same => n,Set(AUDIOSOCKET_UUID=33333333-3333-3333-3333-333333333333)
 ; Caller is now bridged with a Local/* channel — ChanSpy works.
 same => n,Dial(Local/${AUDIOSOCKET_UUID}@pwdemo-clinic-audiosocket/n)
 same => n,Hangup()

[pwdemo-clinic-audiosocket]
exten => _.,1,NoOp(AudioSocket leg for ${EXTEN})
 same => n,Answer()
 same => n,AudioSocket(${EXTEN},192.168.100.25:8092)
 same => n,Hangup()
```

(Replace `192.168.100.25` with your backend host's LAN IP.) Reload:
```bash
/usr/sbin/asterisk -rx "dialplan reload"
```

### Per-machine setup checklist — Clinic Configuration page

Once FreePBX is ready, open `/demo/clinic/call-center/configuration` and
scroll to **Supervisor escalation triggers**:

1. **Supervisor extension** → the PBX extension the operator wants ringing on flag (e.g. `1003`).
2. **PBX integration (AMI)** subsection:
   - **AMI host** = FreePBX LAN IP
   - **AMI port** = `5038`
   - **AMI username** = `pwdemo-clinic` (or whatever you set above)
   - **AMI secret** = the secret from step 2 (password-masked input)
3. **Save** (top-right of the card).

The button states `Saved — takes effect on the next call`. No restart
needed — the service rereads `escalation.json` on every action.

### How a dial-supervisor click flows end-to-end

```
[operator clicks Listen / Whisper / Barge]
  → POST /api/demo/clinic/agent/calls/{call_id}/dial_supervisor?mode={mode}
  → router.py reads escalation.json (ami_host/user/secret + supervisor_extension)
  → ami.py AMIService.dial_supervisor():
       1. Open TCP to ami_host:5038
       2. Action: Login (drops conn + retries on failure)
       3. Action: CoreShowChannels  → find channel running app=AudioSocket
       4. Action: Originate Channel=Local/{ext}@from-internal/n
                  Application=ChanSpy Data=<target>,<opts>
                  where <opts> = qso (listen) | qsow (whisper) | qsoB (barge)
       5. Action: Logoff
  → returns {ok, mode, target_channel, raw, error}
  → button shows "Ringing" for 3.5s, then idles
  → supervisor's phone rings via FreePBX dialplan
  → on answer, ChanSpy hooks them into the live call
```

ChanSpy options (`qso[Bw]`):

| Letter | Effect |
| --- | --- |
| `q` | quiet — no beep before connecting |
| `s` | skip the spoken channel-name announcement |
| `o` | only this channel — don't loop to siblings if it ends |
| `w` | **whisper** — supervisor's voice goes only to the spied (caller) leg |
| `B` | **barge** — supervisor's voice goes to BOTH sides of the bridge |
| (none of w/B) | silent listen — pure monitor |

### Known limits / future work

- **No audio in any mode** without the dialplan refactor above. Symptom: supervisor hears the caller but not Gemini. Fix: the Local-channel pair.
- **Multi-concurrent calls**: the dial-in picks the most recently started AudioSocket channel. For ≤2 concurrent calls this is fine; for >2 you may need to extend `dial_supervisor` to filter by some per-call key (e.g. caller phone number injected via dialplan).
- **Auto-detect (keyword match in transcripts + consecutive tool-error counter)** — the Configuration page has the toggles + threshold inputs and they persist, but the backend code that READS them and auto-fires `flag_for_supervisor` without the agent's involvement isn't wired yet. Today the agent decides to flag (per the persona's contextual ESCALATION rules); auto-detect is a server-side belt around those braces.

---

## 6d. Live Agent — recent persona + tool hardening (IMPLEMENTED)

A batch of smaller fixes that landed alongside §6c, all driven by
real-call regressions. Bundled here so the other machine knows what
behaviour changed.

### Echo gate + VAD sensitivity (sip_live_rep.py + clinic live_agent.py)

Two services were both freezing for ~10 seconds mid-sentence and
producing garbled input_audio_transcription output. Root cause: agent
audio echoing back through speakerphone / weak echo-cancellation →
caller mic → forwarded to Gemini → high-sensitivity VAD classified it
as user speech → Gemini self-interrupted. Two changes per service:

- **Echo gate is now always-on**. Caller audio is dropped for ~350ms past the end of the agent's last outgoing frame, regardless of `interruption_enabled`. The gate window is short enough that real barge-in still works — the caller's next syllable lands as soon as the agent stops talking.
- **`start_of_speech_sensitivity` dropped from `HIGH` → `LOW`**. Faint echo / breathing / line noise no longer trips the speech classifier. End-of-speech sensitivity stays `HIGH` so the agent still notices when the caller stops.

### Frontend transcript garbage filter (`looksLikeGarbage`)

Even with the echo gate, Gemini occasionally hallucinates Korean /
Chinese / German fragments out of low-energy audio. The Dashboard's
`LiveCallsTable` filters caller turns where >40% of the non-whitespace
characters fall outside Arabic + Latin scripts; flagged turns render as
a dashed muted bubble reading `[unintelligible audio]`. Hides the
symptom while we leave the upstream audio-quality work for later.

### Persona — context-first escalation

Earlier draft of the ESCALATION block was a keyword checklist. Rewrote
to **judgment-first**: agent flags whenever the caller sounds angry /
frustrated / asks for a human / repeats a request / threatens to
complain / mentions a medical emergency — **interpret broadly, ignore
exact wording**. Operator-saved keywords/scenarios are still injected
but now framed as **"Operator-provided hints (illustrative, NOT a
closed list)"**. The Configuration UI labels match: "Keyword examples"
not "Keyword triggers".

### Persona — re-flag is encouraged

Earlier draft said "Flag ONCE per cause" — broke the demo when an
operator acknowledged a flag and the caller again asked for a manager
(agent thought it had already flagged that cause and stayed silent).
New rule: **"Re-flag every time a trigger occurs again. Multiple flags
on the same call signal escalating urgency and are NEVER spam."**

### Persona — date awareness (today + tomorrow + day-after)

Symptom: agent said "tomorrow is the 15th" when today was the 17th.
Root cause: agent doing mental arithmetic on the weekday name.
`_build_system_instruction()` now precomputes and injects the three
absolute dates in `YYYY-MM-DD` form. New rule: *"When the caller says
'tomorrow' / 'بكرة' / 'غداً', use the EXACT date from the 'Tomorrow'
line. NEVER recompute from the weekday name."*

### Persona — speak digits one at a time

For phone numbers / national IDs / file numbers / appointment IDs:
always **digit-by-digit** (`"A, seven, zero, zero"` not `"A seven
hundred"`). Reason: callers transcribe digits reliably, cardinals
ambiguously. Exception carved out for natural quantities — durations,
ages, prices, dates.

### Persona — gender: never ask

Symptom: agent asked a male caller for their gender and recorded the
answer wrong. New rule (in CRITICAL GUARDRAILS): **NEVER ASK the
caller about gender**. Always infer from voice timbre + first name +
honorifics. If genuinely unsure, leave empty — reception fills in at
the desk. *"An empty gender is fine. A WRONG gender is not."*

### Persona + tool — slot discipline (booking + reschedule)

Symptom: agent offered times like 16:45 when the clinic runs on a
30-minute grid (16:30, 17:00…), or off-hours like 18:30 when the
clinic closes at 17:00. Defence in depth:

- **Tool layer** (`agent_tools.py _t_create_appointment` + `_t_reschedule_appointment`): hard-rejected — `time` must be in `_slots_for_day(day)` (the same generator `list_free_slots` uses). The error message tells the agent to re-run `list_free_slots`.
- **Persona layer** (`_GUARDRAILS`): explicit rule that the clinic runs on a fixed 30-minute grid; never round/snap silently; the last tool you should have called before any booking is `list_free_slots`; re-run if the caller drifts to a different day or specialty.

### Tool — phone normalisation in `create_patient`

`agent_tools.py` `_format_saudi_mobile(s)` canonicalises any reasonable
Saudi-mobile shape to E.164 `+9665XXXXXXXX`:

| Caller said | Stored as |
| --- | --- |
| `0501234567` | `+966501234567` |
| `501234567` | `+966501234567` |
| `+966 50 123 4567` | `+966501234567` |
| `00966 501234567` | `+966501234567` |
| `0601234567` (wrong prefix) | `""` (empty — reception fixes at desk) |
| `+1 555 0100` (not Saudi) | `""` |

Validation enforces exactly 9 digits after country code starting with
`5`. Invalid input stores empty rather than raising — keeps the patient
record creation succeeding even if the caller can't give a usable
mobile. 10/10 unit-test cases pass.

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
