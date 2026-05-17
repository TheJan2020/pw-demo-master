import{c as w,u as P,j as i}from"./index-CZw767Zv.js";import{B as C}from"./button-CnW6UUZW.js";import{T as M}from"./textarea-BD8jcK-v.js";import{w as I,D as _,j as R,l as g,s as O,i as B,e as L,t as X,u as k,S as F,b as Y,g as H,c as U,C as G}from"./demoStore-CoHr9FDS.js";import{R as K}from"./rotate-ccw-CIVdXj0Z.js";import{c as V}from"./createLucideIcon-PtOkldQh.js";import{C as W}from"./check-DhOTkGbM.js";import{C as z}from"./copy--vRk1pRc.js";const q=[["path",{d:"M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z",key:"1c8476"}],["path",{d:"M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7",key:"1ydtos"}],["path",{d:"M7 3v4a1 1 0 0 0 1 1h7",key:"t51u73"}]],Q=V("save",q),J="pwdemo:clinic:doc",Z=1,S="pwdemo:clinic:doc-change";function $(a){return`${J}:${a}:v${Z}`}function ee(a,r){const[u,c]=w.useState(()=>{if(typeof window>"u")return r;try{return localStorage.getItem($(a))??r}catch{return r}});w.useEffect(()=>{if(typeof window>"u")return;const l=m=>{if(m.detail?.key===a)try{const d=localStorage.getItem($(a));d!==null&&c(d)}catch{}};return window.addEventListener(S,l),()=>window.removeEventListener(S,l)},[a]);const s=w.useCallback(l=>{c(l);try{localStorage.setItem($(a),l)}catch{}window.dispatchEvent(new CustomEvent(S,{detail:{key:a}}))},[a]),o=w.useCallback(()=>{c(r);try{localStorage.removeItem($(a))}catch{}window.dispatchEvent(new CustomEvent(S,{detail:{key:a}}))},[a,r]);return{value:u,set:s,reset:o}}const ue=`# Primewave Mate Clinics — Riyadh

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
`,me=`# Layla — Receptionist persona for Primewave Mate Clinics

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
`;function te({clinics:a,providers:r,appointments:u,overrides:c,lang:s}){const o=[],l=new Date,m=T(l),p=I(l);o.push("# Live clinic state (auto-generated — do NOT edit, refreshes per call)"),o.push(`Generated at: ${l.toISOString()}`),o.push(""),o.push(`## Clinics (${a.length} total)`);for(const e of a){const n=e.head_id?r.find(v=>v.id===e.head_id):null,t=(e.working_hours??_)[R(m)],h=t.open?`${t.open_time}–${t.close_time}${t.break_enabled?` (break ${t.break_start}–${t.break_end})`:""}`:"CLOSED today";o.push(`- ${g(e.name,e.name_ar,s)} · ${g(e.location,e.location_ar,s)} · ${g(e.specialty,e.specialty_ar,s)}`+(n?` · head: ${g(n.name,n.name_ar,s)}`:"")+` · today: ${h}`+(e.active?"":" · INACTIVE"))}o.push("");const d=r.filter(e=>e.active),b={};for(const e of d)b[e.role]=b[e.role]?[...b[e.role],e]:[e];o.push(`## Active staff (${d.length} total)`);for(const e of["doctor","nurse","tech","admin"]){const n=b[e]??[];if(n.length!==0){o.push(`- **${e}** (${n.length}):`);for(const t of n)o.push(`  - ${g(t.name,t.name_ar,s)} · ${g(t.specialty,t.specialty_ar,s)} · ${t.phone}`)}}o.push(""),o.push(`## Today's schedule (${m})`);const y=oe(m,a,u,c);o.push(`Across all clinics — slots ${y.totalSlots} · booked ${y.booked} · blocked ${y.blocked} · free ${y.free}`);for(const e of a){const n=j(e,m,u,c);if(n.totalSlots===0){o.push(`- ${g(e.name,e.name_ar,s)}: closed today`);continue}const t=n.freeSlots.slice(0,4).join(", ")||"(none)";o.push(`- ${g(e.name,e.name_ar,s)}: ${n.free} free of ${n.totalSlots}`+(n.blocked>0?` (${n.blocked} blocked)`:"")+` — first free: ${t}`)}o.push(""),o.push("## This week summary");for(const e of a){let n=0,t=0,h=0;for(const v of p){const x=j(e,v,u,c);h+=x.totalSlots,n+=x.booked,t+=x.blocked}o.push(`- ${g(e.name,e.name_ar,s)}: slots ${h} · booked ${n} · blocked ${t} · free ${Math.max(0,h-n-t)}`)}o.push("");const f=c.filter(e=>e.date>=m);if(f.length>0){o.push(`## Active slot blocks (${f.length} dates)`);const e=[...f].sort((n,t)=>n.date.localeCompare(t.date));for(const n of e.slice(0,20)){const t=a.find(v=>v.id===n.department_id),h=t?g(t.name,t.name_ar,s):n.department_id;o.push(`- ${n.date} — ${h}: ${n.blocked_slots.length} slots blocked (${n.blocked_slots.slice(0,8).join(", ")}${n.blocked_slots.length>8?"…":""})`)}e.length>20&&o.push(`- …and ${e.length-20} more.`),o.push("")}return o.join(`
`)}function T(a){const r=a.getFullYear(),u=String(a.getMonth()+1).padStart(2,"0"),c=String(a.getDate()).padStart(2,"0");return`${r}-${u}-${c}`}function j(a,r,u,c){const s=(a.working_hours??_)[R(r)];if(!s.open)return{totalSlots:0,booked:0,blocked:0,free:0,freeSlots:[]};const o=O(s).filter(t=>!B(t,s)),l=L(u,r,a.id),m=new Set(c.filter(t=>t.department_id===a.id&&t.date===r).flatMap(t=>t.blocked_slots)),p=new Date,d=T(p),b=p.getHours()*60+p.getMinutes(),y=r===d,f=[];let e=0,n=0;for(const t of o){if(l.has(t)){e++;continue}if(m.has(t)){n++;continue}y&&X(t)<b||f.push(t)}return{totalSlots:o.length,booked:e,blocked:n,free:f.length,freeSlots:f}}function oe(a,r,u,c){let s=0,o=0,l=0,m=0;for(const p of r){const d=j(p,a,u,c);s+=d.totalSlots,o+=d.booked,l+=d.blocked,m+=d.free}return{totalSlots:s,booked:o,blocked:l,free:m}}function he({heading:a,description:r,storageKey:u,defaultText:c}){const{t:s,lang:o}=P(),{value:l,set:m,reset:p}=ee(u,c),[d,b]=w.useState(l);w.useEffect(()=>{b(l)},[l]);const y=d!==l,{items:f}=k("departments",F),{items:e}=k("providers",Y),{items:n}=k("appointments",H),{items:t}=k("slot_overrides",U),h=w.useMemo(()=>te({clinics:f,providers:e,appointments:n,overrides:t,lang:o}),[f,e,n,t,o]),v=`${l.trim()}

${h}`.trim(),[x,N]=w.useState(!1),D=async()=>{try{await navigator.clipboard.writeText(v),N(!0),setTimeout(()=>N(!1),1500)}catch{}};return i.jsxs("div",{className:"space-y-6",children:[i.jsxs("div",{className:"flex flex-wrap items-end justify-between gap-3",children:[i.jsxs("div",{children:[i.jsx("h1",{className:"text-2xl font-semibold tracking-tight text-foreground",children:a}),i.jsx("p",{className:"mt-1 max-w-3xl text-sm text-muted-foreground",children:r})]}),i.jsxs("div",{className:"flex items-center gap-2",children:[y?i.jsxs("span",{className:"text-xs text-amber-600 dark:text-amber-400",children:["● ",s("unsavedChanges")]}):i.jsx("span",{className:"text-xs text-muted-foreground",children:s("saved")}),i.jsxs(C,{variant:"outline",onClick:p,children:[i.jsx(K,{className:"me-2 h-4 w-4"}),s("resetToDefault")]}),i.jsxs(C,{onClick:()=>m(d),disabled:!y,children:[i.jsx(Q,{className:"me-2 h-4 w-4"}),s("save")]})]})]}),i.jsx(E,{title:s("editableSection"),meta:`${d.length.toLocaleString()} chars`,children:i.jsx("div",{className:"p-4",children:i.jsx(M,{value:d,onChange:A=>b(A.target.value),rows:18,dir:"auto",className:"resize-y font-mono text-[12.5px] leading-relaxed"})})}),i.jsx(E,{title:s("liveStatePreview"),meta:`${h.length.toLocaleString()} chars · auto`,children:i.jsx("pre",{className:"max-h-[420px] overflow-auto whitespace-pre-wrap p-4 font-mono text-[12px] leading-relaxed text-muted-foreground",dir:"auto",children:h})}),i.jsx(E,{title:s("compiledPrompt"),meta:`${v.length.toLocaleString()} chars`,headerExtra:i.jsxs(C,{size:"sm",variant:"outline",onClick:A=>{A.stopPropagation(),D()},children:[x?i.jsx(W,{className:"me-1.5 h-3.5 w-3.5"}):i.jsx(z,{className:"me-1.5 h-3.5 w-3.5"}),s(x?"copied":"copyPrompt")]}),children:i.jsx("pre",{className:"max-h-[480px] overflow-auto whitespace-pre-wrap p-4 font-mono text-[12px] leading-relaxed text-foreground",dir:"auto",children:v})})]})}function E({title:a,meta:r,headerExtra:u,children:c}){const[s,o]=w.useState(!1);return i.jsxs("div",{className:"overflow-hidden rounded-xl border border-border bg-card",children:[i.jsxs("button",{type:"button",onClick:()=>o(l=>!l),"aria-expanded":s,className:"flex w-full items-center justify-between gap-3 border-b border-border bg-card px-5 py-3 text-start hover:bg-accent/40 transition-colors",children:[i.jsxs("div",{className:"flex items-center gap-2",children:[i.jsx(G,{className:`h-4 w-4 text-muted-foreground transition-transform ${s?"rotate-0":"-rotate-90"}`}),i.jsx("h2",{className:"text-sm font-semibold text-card-foreground",children:a})]}),i.jsxs("div",{className:"flex items-center gap-3",children:[r&&i.jsx("span",{className:"text-xs text-muted-foreground",children:r}),u]})]}),s&&c]})}export{ue as D,he as P,me as a};
