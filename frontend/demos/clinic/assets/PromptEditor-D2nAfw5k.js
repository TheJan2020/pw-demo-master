import{c as k,u as I,j as n}from"./index-BKVBwFQE.js";import{B as D}from"./button-DaKQncX_.js";import{T as P}from"./textarea-t2DVfvnS.js";import{w as L,D as R,k as M,l as w,s as O,i as B,f as F,t as X,u as A,a as Y,c as H,g as U,d as G}from"./demoStore-n5h5GjKy.js";import{R as W}from"./rotate-ccw-DvKVHdPz.js";import{c as z}from"./createLucideIcon-Dn88ohIr.js";import{C as K}from"./check-DTo5_0PT.js";import{C as V}from"./copy-kolwGO1q.js";import{C as q}from"./chevron-down-BHgUh6n6.js";const Q=[["path",{d:"M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z",key:"1c8476"}],["path",{d:"M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7",key:"1ydtos"}],["path",{d:"M7 3v4a1 1 0 0 0 1 1h7",key:"t51u73"}]],Z=z("save",Q),J="pwdemo:clinic:doc",ee=1,E="pwdemo:clinic:doc-change";function _(a){return`${J}:${a}:v${ee}`}function te(a,r){const[h,c]=k.useState(()=>{if(typeof window>"u")return r;try{return localStorage.getItem(_(a))??r}catch{return r}});k.useEffect(()=>{if(typeof window>"u")return;const l=d=>{if(d.detail?.key===a)try{const m=localStorage.getItem(_(a));m!==null&&c(m)}catch{}};return window.addEventListener(E,l),()=>window.removeEventListener(E,l)},[a]);const i=k.useCallback(l=>{c(l);try{localStorage.setItem(_(a),l)}catch{}window.dispatchEvent(new CustomEvent(E,{detail:{key:a}}))},[a]),e=k.useCallback(()=>{c(r);try{localStorage.removeItem(_(a))}catch{}window.dispatchEvent(new CustomEvent(E,{detail:{key:a}}))},[a,r]);return{value:h,set:i,reset:e}}const ge=`# Primewave Mate Clinics — Riyadh

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
`,ye=`# Layla — Receptionist persona for Primewave Mate Clinics

You are **Layla** (ليلى), the AI receptionist for Primewave Mate Clinics in
Riyadh. You answer phone calls and route them politely and efficiently.

## Voice & tone
- Warm, professional, and concise. Never robotic.
- Use the caller's first name after they share it. Apply honorifics
  ("استاذ", "Mr.", "Dr.") when appropriate.
- Sentences short. One question at a time.

## Language — Arabic by default
- **Always greet in Arabic.** Use the Najdi / Hijazi style.
- **Listen to the caller's first reply** and detect their language:
  - If they reply in **English**, switch fully to English from your next
    sentence onward — don't apologise, just do it smoothly.
  - If they reply in **Urdu, Tagalog, French, or another language**,
    switch to that language if you can; otherwise stay in English.
  - If they **mix Arabic and English** (common in Saudi Arabia), match
    their blend naturally — don't force them back to pure Arabic.
- Once you've switched, stay in that language for the rest of the call
  unless the caller switches again.

## Greeting (always in Arabic, exactly this opening)
"السلام عليكم، عيادات برايم ميت. أنا ليلى. كيف أقدر أخدمك؟"
(Hello — Primewave Mate Clinics, this is Layla. How can I help you today?)

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
`;function oe({clinics:a,providers:r,appointments:h,overrides:c,lang:i}){const e=[],l=new Date,d=j(l),g=L(l);e.push("# Live clinic state (auto-generated — do NOT edit, refreshes per call)"),e.push(`Generated at: ${l.toISOString()}`),e.push(""),e.push(`## Clinics (${a.length} total)`);for(const t of a){const s=t.head_id?r.find(b=>b.id===t.head_id):null,o=(t.working_hours??R)[M(d)],p=o.open?`${o.open_time}–${o.close_time}${o.break_enabled?` (break ${o.break_start}–${o.break_end})`:""}`:"CLOSED today";e.push(`- ${w(t.name,t.name_ar,i)} · ${w(t.location,t.location_ar,i)} · ${w(t.specialty,t.specialty_ar,i)}`+(s?` · head: ${w(s.name,s.name_ar,i)}`:"")+` · today: ${p}`+(t.active?"":" · INACTIVE"))}e.push("");const m=r.filter(t=>t.active),f={};for(const t of m)f[t.role]=f[t.role]?[...f[t.role],t]:[t];e.push(`## Active staff (${m.length} total)`);for(const t of["doctor","nurse","tech","admin"]){const s=f[t]??[];if(s.length!==0){e.push(`- **${t}** (${s.length}):`);for(const o of s)e.push(`  - ${w(o.name,o.name_ar,i)} · ${w(o.specialty,o.specialty_ar,i)} · ${o.phone}`)}}e.push("");const y=ie(d,a,h,c);e.push(`## Today's totals (${d})`),e.push(`Across all clinics — slots ${y.totalSlots} · booked ${y.booked} · blocked ${y.blocked} · free ${y.free}`),e.push("");const x=7,v=6,S=[];{const t=new Date;t.setHours(0,0,0,0);for(let s=0;s<x;s++){const o=new Date(t);o.setDate(t.getDate()+s),S.push(j(o))}}e.push(`## Free slots — today and next ${x-1} days (per clinic)`);for(const t of a){e.push(`### ${w(t.name,t.name_ar,i)} — ${w(t.specialty,t.specialty_ar,i)}`);for(const s of S){const o=T(t,s,h,c),p=ne(s,i);if(o.totalSlots===0){e.push(`- ${p}: closed`);continue}if(o.free===0){e.push(`- ${p}: FULL (${o.booked} booked${o.blocked>0?`, ${o.blocked} blocked`:""})`);continue}const b=o.freeSlots.slice(0,v).join(", "),$=o.freeSlots.length>v?` +${o.freeSlots.length-v} more`:"";e.push(`- ${p}: ${b}${$}  (${o.free} of ${o.totalSlots} free)`)}e.push("")}e.push("## This week totals (per clinic)");for(const t of a){let s=0,o=0,p=0;for(const b of g){const $=T(t,b,h,c);p+=$.totalSlots,s+=$.booked,o+=$.blocked}e.push(`- ${w(t.name,t.name_ar,i)}: slots ${p} · booked ${s} · blocked ${o} · free ${Math.max(0,p-s-o)}`)}e.push("");const u=c.filter(t=>t.date>=d);if(u.length>0){e.push(`## Active slot blocks (${u.length} dates)`);const t=[...u].sort((s,o)=>s.date.localeCompare(o.date));for(const s of t.slice(0,20)){const o=a.find(b=>b.id===s.department_id),p=o?w(o.name,o.name_ar,i):s.department_id;e.push(`- ${s.date} — ${p}: ${s.blocked_slots.length} slots blocked (${s.blocked_slots.slice(0,8).join(", ")}${s.blocked_slots.length>8?"…":""})`)}t.length>20&&e.push(`- …and ${t.length-20} more.`),e.push("")}return e.join(`
`)}function j(a){const r=a.getFullYear(),h=String(a.getMonth()+1).padStart(2,"0"),c=String(a.getDate()).padStart(2,"0");return`${r}-${h}-${c}`}const ae=["Sun","Mon","Tue","Wed","Thu","Fri","Sat"],se=["الأحد","الإثنين","الثلاثاء","الأربعاء","الخميس","الجمعة","السبت"];function ne(a,r){const[h,c,i]=a.split("-").map(y=>parseInt(y,10)),e=new Date(h,c-1,i),l=new Date;l.setHours(0,0,0,0);const d=Math.round((e.getTime()-l.getTime())/864e5),g=(r==="ar"?se:ae)[e.getDay()],m=e.toLocaleDateString(r==="ar"?"ar-EG":void 0,{day:"numeric",month:"short"}),f=`${g} ${m}`;return d===0?`Today (${f})`:d===1?`Tomorrow (${f})`:f}function T(a,r,h,c){const i=(a.working_hours??R)[M(r)];if(!i.open)return{totalSlots:0,booked:0,blocked:0,free:0,freeSlots:[]};const e=O(i).filter(u=>!B(u,i)),l=F(h,r,a.id),d=new Set(c.filter(u=>u.department_id===a.id&&u.date===r).flatMap(u=>u.blocked_slots)),g=new Date,m=j(g),f=g.getHours()*60+g.getMinutes(),y=r===m,x=[];let v=0,S=0;for(const u of e){if(l.has(u)){v++;continue}if(d.has(u)){S++;continue}y&&X(u)<f||x.push(u)}return{totalSlots:e.length,booked:v,blocked:S,free:x.length,freeSlots:x}}function ie(a,r,h,c){let i=0,e=0,l=0,d=0;for(const g of r){const m=T(g,a,h,c);i+=m.totalSlots,e+=m.booked,l+=m.blocked,d+=m.free}return{totalSlots:i,booked:e,blocked:l,free:d}}function be({heading:a,description:r,storageKey:h,defaultText:c,showLivePreview:i=!0}){const{t:e,lang:l}=I(),{value:d,set:g,reset:m}=te(h,c),[f,y]=k.useState(d);k.useEffect(()=>{y(d)},[d]);const x=f!==d,{items:v}=A("departments",Y),{items:S}=A("providers",H),{items:u}=A("appointments",U),{items:t}=A("slot_overrides",G),s=k.useMemo(()=>oe({clinics:v,providers:S,appointments:u,overrides:t,lang:l}),[v,S,u,t,l]),o=`${d.trim()}

${s}`.trim(),[p,b]=k.useState(!1),$=async()=>{try{await navigator.clipboard.writeText(o),b(!0),setTimeout(()=>b(!1),1500)}catch{}};return n.jsxs("div",{className:"space-y-6",children:[n.jsxs("div",{className:"flex flex-wrap items-end justify-between gap-3",children:[n.jsxs("div",{children:[n.jsx("h1",{className:"text-2xl font-semibold tracking-tight text-foreground",children:a}),n.jsx("p",{className:"mt-1 max-w-3xl text-sm text-muted-foreground",children:r})]}),n.jsxs("div",{className:"flex items-center gap-2",children:[x?n.jsxs("span",{className:"text-xs text-amber-600 dark:text-amber-400",children:["● ",e("unsavedChanges")]}):n.jsx("span",{className:"text-xs text-muted-foreground",children:e("saved")}),n.jsxs(D,{variant:"outline",onClick:m,children:[n.jsx(W,{className:"me-2 h-4 w-4"}),e("resetToDefault")]}),n.jsxs(D,{onClick:()=>g(f),disabled:!x,children:[n.jsx(Z,{className:"me-2 h-4 w-4"}),e("save")]})]})]}),n.jsx(N,{title:e("editableSection"),meta:`${f.length.toLocaleString()} chars`,children:n.jsx("div",{className:"p-4",children:n.jsx(P,{value:f,onChange:C=>y(C.target.value),rows:18,dir:"auto",className:"resize-y font-mono text-[12.5px] leading-relaxed"})})}),i&&n.jsx(N,{title:e("liveStatePreview"),meta:`${s.length.toLocaleString()} chars · auto`,children:n.jsx("pre",{className:"max-h-[420px] overflow-auto whitespace-pre-wrap p-4 font-mono text-[12px] leading-relaxed text-muted-foreground",dir:"auto",children:s})}),n.jsx(N,{title:e("compiledPrompt"),meta:`${o.length.toLocaleString()} chars`,headerExtra:n.jsxs(D,{size:"sm",variant:"outline",onClick:C=>{C.stopPropagation(),$()},children:[p?n.jsx(K,{className:"me-1.5 h-3.5 w-3.5"}):n.jsx(V,{className:"me-1.5 h-3.5 w-3.5"}),e(p?"copied":"copyPrompt")]}),children:n.jsx("pre",{className:"max-h-[480px] overflow-auto whitespace-pre-wrap p-4 font-mono text-[12px] leading-relaxed text-foreground",dir:"auto",children:o})})]})}function N({title:a,meta:r,headerExtra:h,children:c}){const[i,e]=k.useState(!1);return n.jsxs("div",{className:"overflow-hidden rounded-xl border border-border bg-card",children:[n.jsxs("button",{type:"button",onClick:()=>e(l=>!l),"aria-expanded":i,className:"flex w-full items-center justify-between gap-3 border-b border-border bg-card px-5 py-3 text-start hover:bg-accent/40 transition-colors",children:[n.jsxs("div",{className:"flex items-center gap-2",children:[n.jsx(q,{className:`h-4 w-4 text-muted-foreground transition-transform ${i?"rotate-0":"-rotate-90"}`}),n.jsx("h2",{className:"text-sm font-semibold text-card-foreground",children:a})]}),n.jsxs("div",{className:"flex items-center gap-3",children:[r&&n.jsx("span",{className:"text-xs text-muted-foreground",children:r}),h]})]}),i&&c]})}export{ge as D,be as P,ye as a};
