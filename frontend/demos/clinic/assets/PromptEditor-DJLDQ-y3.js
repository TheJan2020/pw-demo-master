import{c as v,u as D,j as s}from"./index-C6vwK9UL.js";import{B as A}from"./button-DqPDpHsf.js";import{T as P}from"./textarea-UpBvlSl2.js";import{w as M,D as E,j as C,l as b,s as I,i as B,e as L,t as O,u as k,S as X,b as F,g as Y,c as H}from"./demoStore-LnYYUHc7.js";import{R as U}from"./rotate-ccw-crSEbiif.js";import{c as G}from"./createLucideIcon-D7hvpMmY.js";import{C as K}from"./check-Bo6VrklY.js";import{C as V}from"./copy--xxfRS68.js";const W=[["path",{d:"M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z",key:"1c8476"}],["path",{d:"M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7",key:"1ydtos"}],["path",{d:"M7 3v4a1 1 0 0 0 1 1h7",key:"t51u73"}]],z=G("save",W),q="pwdemo:clinic:doc",Q=1,S="pwdemo:clinic:doc-change";function $(n){return`${q}:${n}:v${Q}`}function J(n,l){const[u,d]=v.useState(()=>{if(typeof window>"u")return l;try{return localStorage.getItem($(n))??l}catch{return l}});v.useEffect(()=>{if(typeof window>"u")return;const r=m=>{if(m.detail?.key===n)try{const c=localStorage.getItem($(n));c!==null&&d(c)}catch{}};return window.addEventListener(S,r),()=>window.removeEventListener(S,r)},[n]);const i=v.useCallback(r=>{d(r);try{localStorage.setItem($(n),r)}catch{}window.dispatchEvent(new CustomEvent(S,{detail:{key:n}}))},[n]),o=v.useCallback(()=>{d(l);try{localStorage.removeItem($(n))}catch{}window.dispatchEvent(new CustomEvent(S,{detail:{key:n}}))},[n,l]);return{value:u,set:i,reset:o}}const ce=`# Primewave Mate Clinics — Riyadh

## About us
Primewave Mate Clinics is a multi-specialty outpatient center in the heart
of Riyadh's Olaya district. We've served the Riyadh community since 2018
with same-day appointments, multilingual staff (Arabic, English, Urdu),
and a single integrated medical record across all clinics in the building.

نحن مركز عيادات متعدد التخصصات في حي العليا بالرياض. نقدّم مواعيد في نفس اليوم،
طاقم متعدد اللغات، وسجل طبي موحّد لجميع العيادات داخل المركز.

## Location & contact
- Main Center: Olaya Street, Olaya, Riyadh 12244, KSA
- Reception: +966 11 234 5678
- WhatsApp: +966 50 111 0000
- Email: hello@primemate.clinic
- Maps: search "Primewave Mate Clinics Olaya".

## Operating hours (default — see live state for today)
- Sunday – Thursday: 09:00 – 17:00 (lunch break 13:00 – 14:00)
- Saturday: 09:00 – 13:00 (morning only)
- Friday: closed
- During Ramadan & official holidays hours may shift; agent should always
  defer to the live state below.

## Insurance & payment
Accepted insurance: BUPA Arabia · Tawuniya · MedGulf · AXA · Globemed.
Also: cash, mada, Visa, Mastercard, Apple Pay.
- Pre-approval required for procedures over SAR 1,000.
- Insurance verification takes ~5 minutes at reception.

## Booking & cancellation policy
- Appointments can be booked up to 30 days in advance.
- Walk-ins accepted subject to availability; booking ahead avoids waiting.
- Free cancellation if at least 4 hours before the slot.
- Inside 4 hours: SAR 100 late-cancellation fee.
- Arriving more than 15 minutes late may forfeit the slot.

## Services & pricing (typical)
- General consultation: SAR 350
- Specialist consultation: SAR 500
- Pediatric consultation: SAR 400
- Dental check-up + cleaning: SAR 450
- X-ray (single view): SAR 200
- Basic ultrasound: SAR 350
- Same-day labs, basic imaging on-site (X-ray, ultrasound).
- Telemedicine follow-ups for established patients.
- Home visits within a 10 km radius (extra SAR 250 fee).

## Languages
Arabic, English, Urdu, Tagalog.

## Common FAQs
- "Do you take walk-ins?" — Yes, but booked patients are seen first.
- "Do I need a referral?" — No, you can book a specialist directly.
- "Do you treat children under 1?" — Yes, in Pediatrics (Al Noor).
- "Can I get a sick note?" — Yes, issued at the end of the visit.
- "Parking?" — Free underground parking, entrance B.
`,de=`# Layla — Receptionist persona for Primewave Mate Clinics

You are **Layla** (ليلى), the AI receptionist for Primewave Mate Clinics in
Riyadh. You answer phone calls and route them politely and efficiently.

## Voice & tone
- Warm, professional, and concise. Never robotic.
- Default to Arabic (Najdi/Hijazi style). Switch to English instantly if
  the caller begins in English.
- Use the caller's first name after they share it. Apply honorifics
  ("استاذ", "Mr.", "Dr.") when appropriate.
- Sentences short. One question at a time.

## Greeting
"السلام عليكم، عيادات برايم ميت. أنا ليلى. كيف أقدر أخدمك؟"
("Hello — Primewave Mate Clinics, this is Layla. How can I help you today?")

## You CAN
- Take new appointment requests — collect patient name, mobile, clinic /
  specialty, preferred date + time, and reason in 1–2 short sentences.
- Read out the next available slot in any clinic from the live state below.
- Reschedule or cancel an existing booking given the patient's file # +
  full name.
- Quote prices for common visits (see the Knowledge Base).
- Explain insurance acceptance and payment methods.
- Offer the WhatsApp number (+966 50 111 0000) for non-urgent inquiries.

## You MUST NOT
- Never give medical diagnoses, treatment advice, or dosage information.
- Never confirm a booking outside the clinic's working hours (use the
  live state for the exact window, including breaks and blocks).
- Never invent a slot that's already booked or blocked.
- If the caller describes an emergency (chest pain, heavy bleeding, loss
  of consciousness, suicidal ideation): tell them to call **997** (Saudi
  Red Crescent) immediately, and stay on the line until they do.

## Booking flow — always confirm in this order
1. Patient full name (ask for Arabic spelling too).
2. Mobile number — must be Saudi format: +9665X XXX XXXX.
3. Existing file number if known (format: A/B/C + 6 digits, e.g. A123456).
4. Preferred clinic / specialty (offer the list from the Knowledge Base).
5. Preferred slot — propose 2–3 actual free slots from the live state.
6. Read back the full booking summary in both Arabic and English, then ask
   the caller to confirm "yes" / "نعم" before finalising.

## End-of-call
- Summarise: name, date/time, clinic, doctor (if known), what to bring.
- Politely close: "ان شاء الله نشوفك. شكراً للاتصال."

## Behaviour cheat-sheet
- Caller says "I want any time tomorrow morning" → propose the earliest 2
  free slots before 12:00 from the live state.
- Caller asks for a specific doctor → check that doctor exists in the
  providers list; if not, suggest the closest specialty match.
- Caller mentions a chronic condition → only collect info, do not advise.
- Background noise / language unclear → ask once politely to repeat.
`;function Z({clinics:n,providers:l,appointments:u,overrides:d,lang:i}){const o=[],r=new Date,m=_(r),f=M(r);o.push("# Live clinic state (auto-generated — do NOT edit, refreshes per call)"),o.push(`Generated at: ${r.toISOString()}`),o.push(""),o.push(`## Clinics (${n.length} total)`);for(const e of n){const a=e.head_id?l.find(x=>x.id===e.head_id):null,t=(e.working_hours??E)[C(m)],h=t.open?`${t.open_time}–${t.close_time}${t.break_enabled?` (break ${t.break_start}–${t.break_end})`:""}`:"CLOSED today";o.push(`- ${b(e.name,e.name_ar,i)} · ${b(e.location,e.location_ar,i)} · ${b(e.specialty,e.specialty_ar,i)}`+(a?` · head: ${b(a.name,a.name_ar,i)}`:"")+` · today: ${h}`+(e.active?"":" · INACTIVE"))}o.push("");const c=l.filter(e=>e.active),g={};for(const e of c)g[e.role]=g[e.role]?[...g[e.role],e]:[e];o.push(`## Active staff (${c.length} total)`);for(const e of["doctor","nurse","tech","admin"]){const a=g[e]??[];if(a.length!==0){o.push(`- **${e}** (${a.length}):`);for(const t of a)o.push(`  - ${b(t.name,t.name_ar,i)} · ${b(t.specialty,t.specialty_ar,i)} · ${t.phone}`)}}o.push(""),o.push(`## Today's schedule (${m})`);const y=ee(m,n,u,d);o.push(`Across all clinics — slots ${y.totalSlots} · booked ${y.booked} · blocked ${y.blocked} · free ${y.free}`);for(const e of n){const a=N(e,m,u,d);if(a.totalSlots===0){o.push(`- ${b(e.name,e.name_ar,i)}: closed today`);continue}const t=a.freeSlots.slice(0,4).join(", ")||"(none)";o.push(`- ${b(e.name,e.name_ar,i)}: ${a.free} free of ${a.totalSlots}`+(a.blocked>0?` (${a.blocked} blocked)`:"")+` — first free: ${t}`)}o.push(""),o.push("## This week summary");for(const e of n){let a=0,t=0,h=0;for(const x of f){const w=N(e,x,u,d);h+=w.totalSlots,a+=w.booked,t+=w.blocked}o.push(`- ${b(e.name,e.name_ar,i)}: slots ${h} · booked ${a} · blocked ${t} · free ${Math.max(0,h-a-t)}`)}o.push("");const p=d.filter(e=>e.date>=m);if(p.length>0){o.push(`## Active slot blocks (${p.length} dates)`);const e=[...p].sort((a,t)=>a.date.localeCompare(t.date));for(const a of e.slice(0,20)){const t=n.find(x=>x.id===a.department_id),h=t?b(t.name,t.name_ar,i):a.department_id;o.push(`- ${a.date} — ${h}: ${a.blocked_slots.length} slots blocked (${a.blocked_slots.slice(0,8).join(", ")}${a.blocked_slots.length>8?"…":""})`)}e.length>20&&o.push(`- …and ${e.length-20} more.`),o.push("")}return o.join(`
`)}function _(n){const l=n.getFullYear(),u=String(n.getMonth()+1).padStart(2,"0"),d=String(n.getDate()).padStart(2,"0");return`${l}-${u}-${d}`}function N(n,l,u,d){const i=(n.working_hours??E)[C(l)];if(!i.open)return{totalSlots:0,booked:0,blocked:0,free:0,freeSlots:[]};const o=I(i).filter(t=>!B(t,i)),r=L(u,l,n.id),m=new Set(d.filter(t=>t.department_id===n.id&&t.date===l).flatMap(t=>t.blocked_slots)),f=new Date,c=_(f),g=f.getHours()*60+f.getMinutes(),y=l===c,p=[];let e=0,a=0;for(const t of o){if(r.has(t)){e++;continue}if(m.has(t)){a++;continue}y&&O(t)<g||p.push(t)}return{totalSlots:o.length,booked:e,blocked:a,free:p.length,freeSlots:p}}function ee(n,l,u,d){let i=0,o=0,r=0,m=0;for(const f of l){const c=N(f,n,u,d);i+=c.totalSlots,o+=c.booked,r+=c.blocked,m+=c.free}return{totalSlots:i,booked:o,blocked:r,free:m}}function me({heading:n,description:l,storageKey:u,defaultText:d}){const{t:i,lang:o}=D(),{value:r,set:m,reset:f}=J(u,d),[c,g]=v.useState(r);v.useEffect(()=>{g(r)},[r]);const y=c!==r,{items:p}=k("departments",X),{items:e}=k("providers",F),{items:a}=k("appointments",Y),{items:t}=k("slot_overrides",H),h=v.useMemo(()=>Z({clinics:p,providers:e,appointments:a,overrides:t,lang:o}),[p,e,a,t,o]),x=`${r.trim()}

${h}`.trim(),[w,j]=v.useState(!1),R=async()=>{try{await navigator.clipboard.writeText(x),j(!0),setTimeout(()=>j(!1),1500)}catch{}};return s.jsxs("div",{className:"space-y-6",children:[s.jsxs("div",{className:"flex flex-wrap items-end justify-between gap-3",children:[s.jsxs("div",{children:[s.jsx("h1",{className:"text-2xl font-semibold tracking-tight text-foreground",children:n}),s.jsx("p",{className:"mt-1 max-w-3xl text-sm text-muted-foreground",children:l})]}),s.jsxs("div",{className:"flex items-center gap-2",children:[y?s.jsxs("span",{className:"text-xs text-amber-600 dark:text-amber-400",children:["● ",i("unsavedChanges")]}):s.jsx("span",{className:"text-xs text-muted-foreground",children:i("saved")}),s.jsxs(A,{variant:"outline",onClick:f,children:[s.jsx(U,{className:"me-2 h-4 w-4"}),i("resetToDefault")]}),s.jsxs(A,{onClick:()=>m(c),disabled:!y,children:[s.jsx(z,{className:"me-2 h-4 w-4"}),i("save")]})]})]}),s.jsxs("div",{className:"rounded-xl border border-border bg-card",children:[s.jsxs("div",{className:"flex items-center justify-between border-b border-border px-5 py-3",children:[s.jsx("h2",{className:"text-sm font-semibold text-card-foreground",children:i("editableSection")}),s.jsxs("span",{className:"text-xs text-muted-foreground",children:[c.length.toLocaleString()," chars"]})]}),s.jsx("div",{className:"p-4",children:s.jsx(P,{value:c,onChange:T=>g(T.target.value),rows:18,dir:"auto",className:"resize-y font-mono text-[12.5px] leading-relaxed"})})]}),s.jsxs("div",{className:"rounded-xl border border-border bg-card",children:[s.jsxs("div",{className:"flex items-center justify-between border-b border-border px-5 py-3",children:[s.jsx("h2",{className:"text-sm font-semibold text-card-foreground",children:i("liveStatePreview")}),s.jsxs("span",{className:"text-xs text-muted-foreground",children:[h.length.toLocaleString()," chars · auto"]})]}),s.jsx("pre",{className:"max-h-[420px] overflow-auto whitespace-pre-wrap p-4 font-mono text-[12px] leading-relaxed text-muted-foreground",dir:"auto",children:h})]}),s.jsxs("div",{className:"rounded-xl border border-border bg-card",children:[s.jsxs("div",{className:"flex items-center justify-between border-b border-border px-5 py-3",children:[s.jsx("h2",{className:"text-sm font-semibold text-card-foreground",children:i("compiledPrompt")}),s.jsxs("div",{className:"flex items-center gap-3",children:[s.jsxs("span",{className:"text-xs text-muted-foreground",children:[x.length.toLocaleString()," chars"]}),s.jsxs(A,{size:"sm",variant:"outline",onClick:R,children:[w?s.jsx(K,{className:"me-1.5 h-3.5 w-3.5"}):s.jsx(V,{className:"me-1.5 h-3.5 w-3.5"}),i(w?"copied":"copyPrompt")]})]})]}),s.jsx("pre",{className:"max-h-[480px] overflow-auto whitespace-pre-wrap p-4 font-mono text-[12px] leading-relaxed text-foreground",dir:"auto",children:x})]})]})}export{ce as D,me as P,de as a};
