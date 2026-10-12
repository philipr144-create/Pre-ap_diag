"use strict";
const $ = id => document.getElementById(id);
const esc = x => String(x ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let catalog, state, currentPage = "overview", selectedSignal = "", signalOptions = "", pendingClear, toastTimer;
const fmt = x => typeof x === "number" ? (Number.isInteger(x)?x.toLocaleString():x.toFixed(2)) : String(x ?? "—");
const pretty = x => JSON.stringify(x,null,2);
const timeText = ts => new Date(ts*1000).toLocaleTimeString([], {hour12:false});
function toast(message,error=false){clearTimeout(toastTimer); $("toast").textContent=message;$("toast").classList.toggle("error",error);$("toast").hidden=false;toastTimer=setTimeout(()=>$("toast").hidden=true,error?11000:4500);}
async function api(path,body){
  const response = await fetch("/api/"+path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json","X-Lab-Request":"1"},body:JSON.stringify(body)});
  let data;try{data=await response.json();}catch{throw Error("Server returned an unreadable response");}
  if(!response.ok)throw Error(data.error || (data.detail ? pretty(data.detail) : response.statusText));
  return data;
}
function bind(id,fn){$(id).addEventListener("click",async event=>{event.preventDefault();const button=event.currentTarget;button.disabled=true;try{await fn();}catch(error){toast(error.message,true);}finally{button.disabled=false;}});}
function showPage(page){currentPage=page;document.querySelectorAll(".page").forEach(s=>s.classList.toggle("active",s.id===page));document.querySelectorAll("nav button").forEach(b=>b.classList.toggle("selected",b.dataset.page===page));$("breadcrumb").textContent=page.toUpperCase();$("page-title").textContent={overview:"Vehicle overview",monitor:"Live signals & CAN",faults:"ECU & fault scan",inspector:"UDS inspector",eas:"Air suspension",recordings:"Recordings & reports",safety:"Permissions & safety",evidence:"Evidence library"}[page];if(page==="recordings")loadRuns().catch(e=>toast(e.message,true));if(state)renderState();}
document.querySelectorAll("[data-page]").forEach(b=>b.addEventListener("click",()=>showPage(b.dataset.page)));
function print(id,data){$(id).hidden=false;$(id).textContent=pretty(data);}
async function loadCatalog(){catalog=await api("catalog");renderCatalog();}
function renderCatalog(){
  const profileOptions=catalog.profiles.map(p=>`<option value="${esc(p.key)}">${esc(p.name)}</option>`).join("");
  ["dtc-ecu","inspect-ecu"].forEach(id=>{const prior=$(id).value;$(id).innerHTML=profileOptions;if(catalog.profiles.some(p=>p.key===prior))$(id).value=prior;});
  $("ecu-checks").innerHTML=catalog.profiles.map(p=>`<div class="scan-ecu"><label class="check"><input type="checkbox" data-ecu="${esc(p.key)}" checked>${esc(p.name)}</label><code>${p.tx.toString(16).toUpperCase()} → ${p.rx.toString(16).toUpperCase()} / ${p.bus}</code></div>`).join("");
  const dbs=Object.keys(catalog.dbcs);
  $("bus-map").innerHTML=[0,1,2].map(bus=>`<label>Bus ${bus}<select id="map-${bus}">${dbs.map(name=>`<option ${catalog.bus_map[bus]===name?"selected":""}>${esc(name)}</option>`).join("")}</select></label>`).join("");
  $("did-table").innerHTML=catalog.dids.map(d=>`<tr><td><code>${esc(d.id)}</code></td><td>${esc(d.name)}</td><td>${esc(d.confidence)}</td></tr>`).join("");
  $("routine-cards").innerHTML=catalog.routines.map(r=>`<div class="routine-card"><span class="badge amber">${esc(r.id)} · DISABLED LIVE</span><h3>${esc(r.name)}</h3><p>${esc(r.meaning)}</p><small>${esc(r.confidence)}</small><p class="muted">${esc(r.reason)}</p></div>`).join("");
  $("blocked-actions").innerHTML=catalog.blocked_actions.map(a=>`<span>${esc(a)}</span>`).join("");
  $("reference-table").innerHTML=catalog.references.map(r=>`<tr><td><a href="/api/references/${encodeURIComponent(r.name)}">${esc(r.name)}</a><small>${r.bytes.toLocaleString()} bytes</small></td><td>${esc(r.use)}</td><td class="hash"><code>${esc(r.sha256)}</code></td></tr>`).join("");
  $("dbc-errors").innerHTML=[...(catalog.decoder_errors||[]),...(catalog.decoder_warnings||[])].map(e=>`<div class="callout">${esc(e.file)}: ${esc(e.error||e.warning)}</div>`).join("");
  $("metric-ecus").textContent=catalog.profiles.length;
  $("metric-dbc").textContent=`${dbs.length} DBCs · ${Object.values(catalog.dbcs).reduce((n,ms)=>n+ms.length,0)} message definitions`;
  $("host-permission").textContent=catalog.permissions.live_diagnostics?"HOST READS ALLOWED":"HOST READS LOCKED";
  renderDBCs();
  $("builders-table").innerHTML=catalog.control_reference_builders.map(b=>`<tr><td><code>${esc(b.name)}</code><small>teslacan.py:${b.line}</small></td><td>${esc(b.arguments.join(", "))}</td><td>${esc(b.description)}</td><td>Disabled<small>${esc(b.reason)}</small></td></tr>`).join("");
}
function renderDBCs(){const q=$("dbc-search").value.toLowerCase();let rows=[];for(const [name,messages] of Object.entries(catalog.dbcs))for(const m of messages)for(const s of m.signals){if(`${name} ${m.name} ${m.address.toString(16)} ${s.name}`.toLowerCase().includes(q))rows.push(`<tr><td>${esc(m.name)}<small>${esc(name)}</small></td><td><code>0x${m.address.toString(16).toUpperCase()}</code><small>${m.length} bytes</small></td><td>${esc(s.name)}</td><td>${s.start}|${s.length}<small>${esc(s.byte_order)} · ${s.signed?"signed":"unsigned"}</small></td><td>${s.scale} / ${s.offset}<small>${esc(s.unit||"—")}</small></td></tr>`);}$("dbc-table").innerHTML=rows.join("")||'<tr><td colspan="5">No matching definitions</td></tr>';}
$("dbc-search").addEventListener("input",()=>catalog&&renderDBCs());
function renderState(){
  $("mode-badge").textContent=state.mode.toUpperCase()+(state.tx_enabled?" · READS ARMED":"");
  $("source-note").textContent=state.fault ? `Transport fault: ${state.fault}` : {offline:"Offline workspace. Choose a source to begin monitoring.",demo:"SYNTHETIC DEMO · These signals and diagnostic responses are not measurements from your car.",replay:"REPLAY ONLY · Recorded frames are displayed locally. Nothing is transmitted to a CAN adapter.",panda:state.tx_enabled?"LIVE PANDA · Guarded diagnostic requests armed. Attestation expires automatically.":"LIVE PANDA · Passive receive and raw recording. Diagnostic transmit is locked."}[state.mode];
  $("source-banner").classList.toggle("warning",!!state.fault);
  $("metric-frames").textContent=state.frames.toLocaleString();$("metric-signals").textContent=state.signals.length.toLocaleString();
  $("metric-permission").textContent=state.tx_enabled?"Armed":"Locked";
  const keyNames=["DI_vehicleSpeed","DI_gear","DI_torqueDriver","DI_motorRPM"];
  $("overview-signals").innerHTML=state.signals.length?keyNames.map(name=>{const s=state.signals.find(s=>s.name===name);return `<div class="state-cell"><span class="overline">${esc(name.replace(/^DI_/,"").replace(/([A-Z])/g," $1"))}</span><strong>${s?esc(name==="DI_gear"?({0:"Invalid",1:"Park",2:"Reverse",3:"Neutral",4:"Drive",7:"SNA"}[s.value]||s.value):fmt(s.value)):"—"} <small>${s?esc(s.unit):""}</small></strong><small>${s?esc(s.source)+" · "+s.age.toFixed(1)+"s old":"Not observed"}</small></div>`;}).join(""):'<p class="empty">No data yet. Start a demo, replay, or passive capture.</p>';
  if(currentPage==="monitor"){
    const query=$("signal-search").value.toLowerCase(),busFilter=$("signal-bus").value,typeFilter=$("signal-type").value;
    $("signal-table").innerHTML=state.signals.filter(s=>`${s.name} ${s.message} ${s.bus} ${s.dbc} ${s.unit}`.toLowerCase().includes(query)&&(!busFilter||String(s.bus)===busFilter)&&(!typeFilter||signalType(s)===typeFilter)).map(s=>`<tr><td><strong>${esc(s.name)}</strong></td><td>${esc(s.message)}<small>Bus ${s.bus} · ${esc(s.dbc)}</small></td><td><code>${esc(fmt(s.value))}</code> ${esc(s.unit)}</td><td>${s.age.toFixed(1)}s<small>${esc(s.source)}${s.age>1?" · STALE":""}</small></td></tr>`).join("") || '<tr><td colspan="4" class="empty">No matching decoded signals</td></tr>';
    const rawQuery=$("raw-search").value.toLowerCase().replace(/^0x/,"");
    $("raw-table").innerHTML=state.raw.slice().reverse().filter(f=>f.address.toString(16).includes(rawQuery)).map(f=>`<tr><td>${timeText(f.ts)}</td><td>${f.bus}</td><td>0x${f.address.toString(16).toUpperCase()}</td><td>${f.data.match(/../g)?.join(" ")||""}</td><td>${esc(f.direction)} / ${esc(f.source)}</td></tr>`).join("");
    const optionsKey=state.signals.map(s=>s.key).join("|");
    if(signalOptions!==optionsKey){signalOptions=optionsKey;const old=selectedSignal;$("graph-signal").innerHTML=state.signals.map(s=>`<option value="${esc(s.key)}">${esc(s.name)} · ${esc(s.message)} · bus ${s.bus}</option>`).join("")||'<option value="">Waiting for decoded signals</option>';selectedSignal=state.signals.some(s=>s.key===old)?old:(state.signals.find(s=>s.name==="DI_torqueDriver")?.key||state.signals[0]?.key||"");$("graph-signal").value=selectedSignal;}
    $("signal-export").href=selectedSignal?"/api/history.csv?key="+encodeURIComponent(selectedSignal):"#";
    updateChart().catch(e=>toast(e.message,true));
    $("replay-seek").max=Math.max(0,state.replay.total-1);$("replay-seek").value=state.replay.index;
    $("replay-position").textContent=state.mode==="replay"?`${state.replay.index.toLocaleString()} / ${state.replay.total.toLocaleString()} frames · ${state.replay.paused?"paused":"playing"}`:"No replay loaded";
  }
  if(currentPage==="faults")renderDTCs();
  const g=state.guard;
  $("interlocks").innerHTML=[
    ["Source",state.mode==="panda",state.mode.toUpperCase()],
    ["Stationary + Park + valid quality",g.fresh_stationary_park,g.fresh_stationary_park?"Fresh live telemetry":"Missing / stale / invalid"],
    ["Car-off / secured attestation",g.attestation_seconds>0,`${g.attestation_seconds}s remaining`],
    ["Transmit mode",state.tx_enabled,state.tx_enabled?"Armed":"Silent"],
    ["Transport quarantine",!state.quarantined,state.quarantined?"Reconnect required":"Clear"]
  ].map(([name,ok,value])=>`<div class="interlock"><span>${esc(name)}</span><b class="${ok?"ok":""}">${esc(value)}</b></div>`).join("");
}
function signalType(s){if(/counter|checksum|crc/i.test(s.name))return "counter";const message=catalog.dbcs[s.dbc]?.find(m=>m.name===s.message),def=message?.signals.find(d=>d.name===s.name);if(def&&(def.length===1||Object.keys(def.choices||{}).length))return "status";return s.unit?"measurement":"other";}
function renderDTCs(){
  const entries=Object.entries(state.dtcs);
  $("dtc-results").className=entries.length?"":"empty";
  $("dtc-results").innerHTML=entries.length?entries.map(([key,r])=>`<h3>${esc(catalog.profiles.find(p=>p.key===key)?.name||key)} <span class="badge">${esc(r.source.toUpperCase())}</span></h3><p class="muted">${timeText(r.ts)} · availability mask ${esc(r.availability_mask)} · ${r.records.length} reported records</p><div class="table-wrap"><table><thead><tr><th>DTC (3 bytes)</th><th>Status</th><th>Available status flags</th><th>Meaning</th></tr></thead><tbody>${r.records.map(d=>`<tr><td><code>${esc(d.code)}</code></td><td><code>${esc(d.status)}</code></td><td>${d.flags.map(f=>`<span class="flag">${esc(f)}</span>`).join("")||"No available set flags"}${d.unsupported_set_bits!=="00"?`<small>Unsupported set bits ${esc(d.unsupported_set_bits)}</small>`:""}</td><td>${esc(d.meaning)}</td></tr>`).join("")||'<tr><td colspan="4">No records returned for this request; vehicle health is not inferred.</td></tr>'}</tbody></table></div><pre class="small-output">${esc(r.raw)}</pre>`).join(""):'No ECU scan performed in this acquisition.';
  $("candidates").innerHTML=state.candidates.length?state.candidates.map(c=>`<p><code>0x${c.rx.toString(16).toUpperCase()}</code> · bus ${c.bus} · ${esc(c.source)}<small> ${esc(c.confidence)}</small></p>`).join(""):"No candidates yet.";
}
let chartBusy=false;
async function updateChart(){
  if(chartBusy||!selectedSignal)return;
  chartBusy=true;
  try{const key=selectedSignal,rows=await api("history?key="+encodeURIComponent(key));if(selectedSignal!==key)return;drawChart(rows);const s=state.signals.find(s=>s.key===key);$("chart-label").textContent=`${s?.name||key} · ${s?.source||""} · last ${rows.length} samples`;}
  finally{chartBusy=false;}
}
function drawChart(rows){
  const canvas=$("chart"),ratio=window.devicePixelRatio||1,w=canvas.clientWidth,h=220;
  if(!w)return;canvas.width=w*ratio;canvas.height=h*ratio;const c=canvas.getContext("2d");c.scale(ratio,ratio);c.clearRect(0,0,w,h);
  const left=54,right=w-15,top=15,bottom=h-25;
  const points=rows.filter(([t,v])=>Number.isFinite(t)&&Number.isFinite(v));
  if(points.length<2){c.fillStyle="#91a4a3";c.font="12px sans-serif";c.fillText("Waiting for signal history…",left,80);return;}
  let lo=Math.min(...points.map(p=>p[1])),hi=Math.max(...points.map(p=>p[1]));const range=hi-lo||1;lo-=range*.12;hi+=range*.12;
  let t0=points[0][0],t1=points.at(-1)[0];if(t1<=t0)t1=t0+1;
  const x=t=>left+(t-t0)/(t1-t0)*(right-left),y=v=>bottom-(v-lo)/(hi-lo)*(bottom-top);
  c.font="10px sans-serif";for(let i=0;i<5;i++){const yy=top+(bottom-top)*i/4;c.strokeStyle="#2e403b";c.beginPath();c.moveTo(left,yy);c.lineTo(right,yy);c.stroke();c.fillStyle="#91a4a3";c.fillText((hi-(hi-lo)*i/4).toFixed(1),0,yy+4);}
  const fill=c.createLinearGradient(0,top,0,bottom);fill.addColorStop(0,"#92d9bb44");fill.addColorStop(1,"#92d9bb00");
  c.beginPath();c.moveTo(x(points[0][0]),bottom);points.forEach(([t,v])=>c.lineTo(x(t),y(v)));c.lineTo(x(points.at(-1)[0]),bottom);c.closePath();c.fillStyle=fill;c.fill();
  c.beginPath();points.forEach(([t,v],i)=>i?c.lineTo(x(t),y(v)):c.moveTo(x(t),y(v)));c.strokeStyle="#9ee0c5";c.lineWidth=2;c.stroke();c.fillStyle="#91a4a3";c.fillText(timeText(t0),left,h-5);c.fillText(timeText(t1),right-55,h-5);
  $("chart-range").textContent=`${Math.min(...points.map(p=>p[1])).toFixed(2)} — ${Math.max(...points.map(p=>p[1])).toFixed(2)}`;
}
async function refresh(){state=await api("state");renderState();}
async function startSource(mode){let body={mode:mode==="panda-spi"?"panda":mode,interface:mode==="panda-spi"?"spi":"usb"};if(mode==="panda"||mode==="panda-spi")body.serial=$("serial").value||null;if(mode==="replay"){const file=$("replay-file").files[0];if(!file)throw Error("Choose a JSONL or candump recording first");if(file.size>24_000_000)throw Error("Recording exceeds 24 MB; split it before importing");body.text=await file.text();body.speed=Number($("replay-speed").value);}await api("source",body);signalOptions="";selectedSignal="";await refresh();toast(mode==="demo"?"Synthetic demo started. No CAN hardware is connected.":"Acquisition started; raw frames are recorded automatically.");}
bind("demo-start",()=>startSource("demo"));bind("connect",()=>startSource($("source").value));
bind("stop",async()=>{await api("stop",{});await refresh();toast("Acquisition stopped and diagnostic access disarmed.");});
bind("devices",async()=>print("device-result",await api("devices")));
bind("source-shortcut",()=>showPage("monitor"));
bind("save-map",async()=>{await api("mapping",{mapping:Object.fromEntries([0,1,2].map(b=>[b,$("map-"+b).value]))});signalOptions="";await loadCatalog();await refresh();toast("Decoder mapping applied. Live interlocks reset.");});
bind("replay-pause",async()=>{await api("replay",{paused:!state.replay.paused});await refresh();});
$("replay-speed").addEventListener("change",()=>{if(state?.mode==="replay")api("replay",{speed:Number($("replay-speed").value)}).catch(e=>toast(e.message,true));});
$("replay-seek").addEventListener("change",()=>api("replay",{index:Number($("replay-seek").value),paused:true}).then(refresh).catch(e=>toast(e.message,true)));
$("graph-signal").addEventListener("change",()=>{selectedSignal=$("graph-signal").value;updateChart().catch(e=>toast(e.message,true));});
["signal-search","raw-search","signal-bus","signal-type"].forEach(id=>$(id).addEventListener("input",()=>state&&renderState()));
bind("scan",async()=>{const keys=[...document.querySelectorAll("[data-ecu]:checked")].map(x=>x.dataset.ecu);print("scan-result",await api("discover",{keys,dry_run:$("scan-dry").checked}));await refresh();});
bind("add-ecu",async()=>{const tx=parseInt($("ecu-tx").value.replace(/^0x/i,""),16),rx=parseInt($("ecu-rx").value.replace(/^0x/i,""),16);if(!Number.isFinite(tx)||!Number.isFinite(rx))throw Error("Enter request and response CAN IDs in hex");await api("profiles",{key:$("ecu-key").value,name:$("ecu-name").value,tx,rx,bus:Number($("ecu-bus").value)});await loadCatalog();toast("Candidate added. Live transmit remains disabled.");});
async function readDTC(ecu){const result=await api("diagnostic",{ecu,action:"read_dtc",dry_run:false});await refresh();toast(`${result.source.toUpperCase()}: DTC response preserved. ${result.records.length} records.`);}
bind("read-dtc",()=>readDTC($("dtc-ecu").value));
bind("eas-dtc",async()=>{await readDTC("eas");showPage("faults");});
bind("eas-plan",async()=>{print("eas-result",await api("diagnostic",{ecu:"eas",action:"read_dtc",dry_run:true}));});
bind("clear-dtc",async()=>{const ecu=$("dtc-ecu").value;pendingClear={...await api("clear/prepare",{ecu}),ecu,source:state.mode};$("clear-context").textContent=`${state.mode.toUpperCase()} · ${ecu.toUpperCase()} · all stored DTCs. Type: ${pendingClear.phrase}`;$("clear-phrase").value="";$("clear-dialog").showModal();$("clear-phrase").focus();});
bind("clear-confirm",async()=>{if(!pendingClear)throw Error("Prepare a new confirmation");const p=pendingClear;pendingClear=null;$("clear-dialog").close();const result=await api("diagnostic",{ecu:p.ecu,action:"clear_dtc",dry_run:false,token:p.token,phrase:$("clear-phrase").value});await refresh();toast(result.note);});
$("clear-dialog").addEventListener("close",()=>{pendingClear=null;});
bind("inspect-send",async()=>{const action=$("inspect-action").value;print("inspect-result",await api("diagnostic",{ecu:$("inspect-ecu").value,action,identifier:action==="read_dtc"?null:$("inspect-id").value,dry_run:$("inspect-dry").checked}));});
$("inspect-action").addEventListener("change",()=>{$("inspect-id").value={read_did:"F190",routine_results:"030A",session:"01",read_dtc:""}[$("inspect-action").value];});
bind("eas-preview",async()=>{const id=$("eas-routine").value;print("eas-result",await api("diagnostic",{ecu:"eas",action:"routine_start",identifier:id,parameter:id==="0305"?$("eas-height").value:null,dry_run:true}));});
bind("arm",async()=>{await api("arm",{car_off:$("car-off").checked,secured:$("secured").checked,exclusive:$("exclusive").checked});await refresh();toast("Guarded reads armed for up to 60 seconds.");});
bind("disarm",async()=>{await api("disarm",{});await refresh();toast("Diagnostic transmit disarmed.");});
async function loadRuns(){const [runs,events]=await Promise.all([api("runs"),api("events")]);$("runs-table").innerHTML=runs.map(r=>`<tr><td><strong>${esc(r.label)}</strong><small>${new Date(r.started*1000).toLocaleString()}</small></td><td><span class="badge">${esc(r.mode.toUpperCase())}</span></td><td>${r.frames.toLocaleString()}</td><td>${r.ended?"Closed · see report":"Open / interrupted"}</td><td><div class="export-links"><a href="/api/runs/${r.id}/frames">JSONL</a><a href="/api/runs/${r.id}/frames?format=csv">CSV</a><a href="/api/runs/${r.id}/report">JSON report</a><a href="/api/runs/${r.id}/report?format=txt">TXT</a></div></td></tr>`).join("")||'<tr><td colspan="5" class="empty">No recordings yet. Start any source to record.</td></tr>';$("audit-events").textContent=events.map(e=>`${timeText(e.ts)} ${e.kind}\n${pretty(e.data)}`).join("\n\n")||"No events.";}
bind("refresh-runs",loadRuns);
bind("add-marker",async()=>{await api("marker",{text:$("marker").value});$("marker").value="";toast("Observation saved to this acquisition.");});
window.addEventListener("resize",()=>{if(currentPage==="monitor")updateChart().catch(()=>{});});
async function poll(){try{await refresh();$("connection-error").hidden=true;}catch(error){$("connection-error").hidden=false;}setTimeout(poll,800);}
async function init(){try{await loadCatalog();await poll();}catch(error){toast(error.message,true);$("connection-error").hidden=false;}}
init();
