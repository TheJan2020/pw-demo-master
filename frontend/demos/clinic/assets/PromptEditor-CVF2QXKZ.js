import{c as k,u as X,j as s}from"./index-CdCvgykI.js";import{B as C}from"./button-uf1q1I2n.js";import{T as B}from"./textarea-1d4tn0m2.js";import{w as F,D as P,p as L,l as x,s as Y,i as H,f as U,t as q,u as N,a as G,c as W,g as z,d as V}from"./demoStore-D3KyCbRb.js";import{R as K}from"./rotate-ccw-CcfPC0M-.js";import{S as Q}from"./save-BGFY_ie8.js";import{c as J}from"./createLucideIcon-EY2SJ9Oz.js";import{C as Z}from"./check-D8YBHmZ5.js";import{C as ee}from"./copy-CevaJsr1.js";import{C as te}from"./chevron-down-B-53KEgB.js";const oe=[["path",{d:"M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z",key:"1ffxy3"}],["path",{d:"m21.854 2.147-10.94 10.939",key:"12cjpa"}]],ae=J("send",oe),ne="pwdemo:clinic:doc",se=1,T="pwdemo:clinic:doc-change";function _(a){return`${ne}:${a}:v${se}`}function ie(a,r){const[h,d]=k.useState(()=>{if(typeof window>"u")return r;try{return localStorage.getItem(_(a))??r}catch{return r}});k.useEffect(()=>{if(typeof window>"u")return;const l=c=>{if(c.detail?.key===a)try{const m=localStorage.getItem(_(a));m!==null&&d(m)}catch{}};return window.addEventListener(T,l),()=>window.removeEventListener(T,l)},[a]);const i=k.useCallback(l=>{d(l);try{localStorage.setItem(_(a),l)}catch{}window.dispatchEvent(new CustomEvent(T,{detail:{key:a}}))},[a]),e=k.useCallback(()=>{d(r);try{localStorage.removeItem(_(a))}catch{}window.dispatchEvent(new CustomEvent(T,{detail:{key:a}}))},[a,r]);return{value:h,set:i,reset:e}}const ve=`# Primewave Mate Clinics — Riyadh

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
`,Se=`# Layla — Receptionist persona for Primewave Mate Clinics

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

## Caller intake flow — RUN THIS FIRST, EVERY CALL
Before booking, rescheduling, or answering questions, establish who's
calling. Follow this script:

1. **Phone lookup.** If a \`lookup_patient_by_phone\` tool is available
   and the system has given you the caller's number, call it. If it
   returns a match, jump straight to "Hello <name>, welcome back —
   how can I help today?" and skip to the request.
2. **If no match (or no tool / no number):** ask politely:
   "هل أنتِ مريض جديد، أم لديكِ ملف عندنا؟" / "Are you a new patient,
   or do you have a file with us already?"
3. **Returning patient path:**
   a. Ask for the **file number** (format: A/B/C + 6 digits — e.g.
      "ألف مية وثلاث وعشرين أربع مية وستة وخمسين").
   b. If the caller doesn't know the file number, ask for:
      - Full name (with Arabic spelling).
      - Date of birth (year + month).
      - National / Iqama ID (10 digits — starts with 1 for Saudi,
        2 for residents).
      Cross-confirm at least two of these match before continuing.
4. **New patient path** — create a file by collecting:
   - Full name (English + Arabic spelling).
   - Mobile number (Saudi format: +9665X XXX XXXX).
   - National / Iqama ID (10 digits — 1xxxxxxxxx Saudi,
     2xxxxxxxxx resident).
   - Date of birth.
   - City of residence.
   - One-line reason for the visit.
   Read the generated file number back at the end so the patient
   has it for next time.
5. **Only after identity is confirmed**, ask what the caller needs and
   move into the booking / question / cancellation flow.

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
`;function re({clinics:a,providers:r,appointments:h,overrides:d,lang:i}){const e=[],l=new Date,c=j(l),g=F(l);e.push("# Live clinic state (auto-generated — do NOT edit, refreshes per call)"),e.push(`Generated at: ${l.toISOString()}`),e.push(""),e.push(`## Clinics (${a.length} total)`);for(const t of a){const n=t.head_id?r.find(w=>w.id===t.head_id):null,o=(t.working_hours??P)[L(c)],f=o.open?`${o.open_time}–${o.close_time}${o.break_enabled?` (break ${o.break_start}–${o.break_end})`:""}`:"CLOSED today";e.push(`- ${x(t.name,t.name_ar,i)} · ${x(t.location,t.location_ar,i)} · ${x(t.specialty,t.specialty_ar,i)}`+(n?` · head: ${x(n.name,n.name_ar,i)}`:"")+` · today: ${f}`+(t.active?"":" · INACTIVE"))}e.push("");const m=r.filter(t=>t.active),p={};for(const t of m)p[t.role]=p[t.role]?[...p[t.role],t]:[t];e.push(`## Active staff (${m.length} total)`);for(const t of["doctor","nurse","tech","admin"]){const n=p[t]??[];if(n.length!==0){e.push(`- **${t}** (${n.length}):`);for(const o of n)e.push(`  - ${x(o.name,o.name_ar,i)} · ${x(o.specialty,o.specialty_ar,i)} · ${o.phone}`)}}e.push("");const y=he(c,a,h,d);e.push(`## Today's totals (${c})`),e.push(`Across all clinics — slots ${y.totalSlots} · booked ${y.booked} · blocked ${y.blocked} · free ${y.free}`),e.push("");const b=7,v=6,A=[];{const t=new Date;t.setHours(0,0,0,0);for(let n=0;n<b;n++){const o=new Date(t);o.setDate(t.getDate()+n),A.push(j(o))}}e.push(`## Free slots — today and next ${b-1} days (per clinic)`);for(const t of a){e.push(`### ${x(t.name,t.name_ar,i)} — ${x(t.specialty,t.specialty_ar,i)}`);for(const n of A){const o=R(t,n,h,d),f=de(n,i);if(o.totalSlots===0){e.push(`- ${f}: closed`);continue}if(o.free===0){e.push(`- ${f}: FULL (${o.booked} booked${o.blocked>0?`, ${o.blocked} blocked`:""})`);continue}const w=o.freeSlots.slice(0,v).join(", "),S=o.freeSlots.length>v?` +${o.freeSlots.length-v} more`:"";e.push(`- ${f}: ${w}${S}  (${o.free} of ${o.totalSlots} free)`)}e.push("")}e.push("## This week totals (per clinic)");for(const t of a){let n=0,o=0,f=0;for(const w of g){const S=R(t,w,h,d);f+=S.totalSlots,n+=S.booked,o+=S.blocked}e.push(`- ${x(t.name,t.name_ar,i)}: slots ${f} · booked ${n} · blocked ${o} · free ${Math.max(0,f-n-o)}`)}e.push("");const u=d.filter(t=>t.date>=c);if(u.length>0){e.push(`## Active slot blocks (${u.length} dates)`);const t=[...u].sort((n,o)=>n.date.localeCompare(o.date));for(const n of t.slice(0,20)){const o=a.find(w=>w.id===n.department_id),f=o?x(o.name,o.name_ar,i):n.department_id;e.push(`- ${n.date} — ${f}: ${n.blocked_slots.length} slots blocked (${n.blocked_slots.slice(0,8).join(", ")}${n.blocked_slots.length>8?"…":""})`)}t.length>20&&e.push(`- …and ${t.length-20} more.`),e.push("")}return e.join(`
`)}function j(a){const r=a.getFullYear(),h=String(a.getMonth()+1).padStart(2,"0"),d=String(a.getDate()).padStart(2,"0");return`${r}-${h}-${d}`}const le=["Sun","Mon","Tue","Wed","Thu","Fri","Sat"],ce=["الأحد","الإثنين","الثلاثاء","الأربعاء","الخميس","الجمعة","السبت"];function de(a,r){const[h,d,i]=a.split("-").map(y=>parseInt(y,10)),e=new Date(h,d-1,i),l=new Date;l.setHours(0,0,0,0);const c=Math.round((e.getTime()-l.getTime())/864e5),g=(r==="ar"?ce:le)[e.getDay()],m=e.toLocaleDateString(r==="ar"?"ar-EG":void 0,{day:"numeric",month:"short"}),p=`${g} ${m}`;return c===0?`Today (${p})`:c===1?`Tomorrow (${p})`:p}function R(a,r,h,d){const i=(a.working_hours??P)[L(r)];if(!i.open)return{totalSlots:0,booked:0,blocked:0,free:0,freeSlots:[]};const e=Y(i).filter(u=>!H(u,i)),l=U(h,r,a.id),c=new Set(d.filter(u=>u.department_id===a.id&&u.date===r).flatMap(u=>u.blocked_slots)),g=new Date,m=j(g),p=g.getHours()*60+g.getMinutes(),y=r===m,b=[];let v=0,A=0;for(const u of e){if(l.has(u)){v++;continue}if(c.has(u)){A++;continue}y&&q(u)<p||b.push(u)}return{totalSlots:e.length,booked:v,blocked:A,free:b.length,freeSlots:b}}function he(a,r,h,d){let i=0,e=0,l=0,c=0;for(const g of r){const m=R(g,a,h,d);i+=m.totalSlots,e+=m.booked,l+=m.blocked,c+=m.free}return{totalSlots:i,booked:e,blocked:l,free:c}}function Ae({heading:a,description:r,storageKey:h,defaultText:d,showLivePreview:i=!0}){const{t:e,lang:l}=X(),{value:c,set:g,reset:m}=ie(h,d),[p,y]=k.useState(c);k.useEffect(()=>{y(c)},[c]);const b=p!==c,{items:v}=N("departments",G),{items:A}=N("providers",W),{items:u}=N("appointments",z),{items:t}=N("slot_overrides",V),n=k.useMemo(()=>re({clinics:v,providers:A,appointments:u,overrides:t,lang:l}),[v,A,u,t,l]),o=`${c.trim()}

${n}`.trim(),[f,w]=k.useState(!1),[S,E]=k.useState("idle"),M=async()=>{try{await navigator.clipboard.writeText(o),w(!0),setTimeout(()=>w(!1),1500)}catch{}},O=async()=>{E("sending");try{const I=await fetch("/api/demo/clinic/agent/prompt",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(h==="persona"?{persona:c}:h==="kb"?{kb:c}:{})});if(!I.ok)throw new Error(`HTTP ${I.status}`);E("ok"),setTimeout(()=>E("idle"),1500)}catch($){console.error("Apply to agent failed:",$),E("err"),setTimeout(()=>E("idle"),2500)}};return s.jsxs("div",{className:"space-y-6",children:[s.jsxs("div",{className:"flex flex-wrap items-end justify-between gap-3",children:[s.jsxs("div",{children:[s.jsx("h1",{className:"text-2xl font-semibold tracking-tight text-foreground",children:a}),s.jsx("p",{className:"mt-1 max-w-3xl text-sm text-muted-foreground",children:r})]}),s.jsxs("div",{className:"flex items-center gap-2",children:[b?s.jsxs("span",{className:"text-xs text-amber-600 dark:text-amber-400",children:["● ",e("unsavedChanges")]}):s.jsx("span",{className:"text-xs text-muted-foreground",children:e("saved")}),s.jsxs(C,{variant:"outline",onClick:m,children:[s.jsx(K,{className:"me-2 h-4 w-4"}),e("resetToDefault")]}),s.jsxs(C,{onClick:()=>g(p),disabled:!b,children:[s.jsx(Q,{className:"me-2 h-4 w-4"}),e("save")]}),s.jsxs(C,{variant:"outline",onClick:O,disabled:S==="sending"||b,title:e(b?"unsavedChanges":"applyToAgent"),children:[s.jsx(ae,{className:"me-2 h-4 w-4"}),e(S==="ok"?"applied":S==="err"?"applyFailed":"applyToAgent")]})]})]}),s.jsx(D,{title:e("editableSection"),meta:`${p.length.toLocaleString()} chars`,children:s.jsx("div",{className:"p-4",children:s.jsx(B,{value:p,onChange:$=>y($.target.value),rows:18,dir:"auto",className:"resize-y font-mono text-[12.5px] leading-relaxed"})})}),i&&s.jsx(D,{title:e("liveStatePreview"),meta:`${n.length.toLocaleString()} chars · auto`,children:s.jsx("pre",{className:"max-h-[420px] overflow-auto whitespace-pre-wrap p-4 font-mono text-[12px] leading-relaxed text-muted-foreground",dir:"auto",children:n})}),s.jsx(D,{title:e("compiledPrompt"),meta:`${o.length.toLocaleString()} chars`,headerExtra:s.jsxs(C,{size:"sm",variant:"outline",onClick:$=>{$.stopPropagation(),M()},children:[f?s.jsx(Z,{className:"me-1.5 h-3.5 w-3.5"}):s.jsx(ee,{className:"me-1.5 h-3.5 w-3.5"}),e(f?"copied":"copyPrompt")]}),children:s.jsx("pre",{className:"max-h-[480px] overflow-auto whitespace-pre-wrap p-4 font-mono text-[12px] leading-relaxed text-foreground",dir:"auto",children:o})})]})}function D({title:a,meta:r,headerExtra:h,children:d}){const[i,e]=k.useState(!1);return s.jsxs("div",{className:"overflow-hidden rounded-xl border border-border bg-card",children:[s.jsxs("button",{type:"button",onClick:()=>e(l=>!l),"aria-expanded":i,className:"flex w-full items-center justify-between gap-3 border-b border-border bg-card px-5 py-3 text-start hover:bg-accent/40 transition-colors",children:[s.jsxs("div",{className:"flex items-center gap-2",children:[s.jsx(te,{className:`h-4 w-4 text-muted-foreground transition-transform ${i?"rotate-0":"-rotate-90"}`}),s.jsx("h2",{className:"text-sm font-semibold text-card-foreground",children:a})]}),s.jsxs("div",{className:"flex items-center gap-3",children:[r&&s.jsx("span",{className:"text-xs text-muted-foreground",children:r}),h]})]}),i&&d]})}export{ve as D,Ae as P,Se as a};
