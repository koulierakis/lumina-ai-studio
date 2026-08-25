(()=>{
'use strict';
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
const ENDPOINTS=['https://overpass-api.de/api/interpreter','https://overpass.kumi.systems/api/interpreter','https://overpass.openstreetmap.fr/api/interpreter','https://overpass.private.coffee/api/interpreter'];
const TYPES={
  fuel:{label:'βενζινάδικο',tags:[['amenity','fuel']]},
  cafe:{label:'καφέ',tags:[['amenity','cafe']]},
  restaurant:{label:'εστιατόριο',tags:[['amenity','restaurant'],['amenity','fast_food']]},
  pharmacy:{label:'φαρμακείο',tags:[['amenity','pharmacy']]},
  hospital:{label:'νοσοκομείο',tags:[['amenity','hospital']]},
  parking:{label:'πάρκινγκ',tags:[['amenity','parking']]}
};
let recognition=null,running=false,enabled=false,manual=false,resumeTimer=null,ignoreUntil=0;
const $=s=>document.querySelector(s);
const rad=v=>v*Math.PI/180;
const dist=(a,b)=>{const R=6371e3,p1=rad(a.lat),p2=rad(b.lat),dp=rad(b.lat-a.lat),dl=rad(b.lng-a.lng),x=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.atan2(Math.sqrt(x),Math.sqrt(1-x))};
const fmt=m=>m<1000?`${Math.round(m)} μέτρα`:`${(m/1000).toFixed(1)} χιλιόμετρα`;
const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('el-GR').replace(/[.,!?;:]+/g,' ').replace(/\s+/g,' ').trim();
const startsWithWake=s=>/^(?:hey\s+)?(?:lumina|λουμινα)\b/i.test(norm(s));
const stripWake=s=>norm(s).replace(/^(?:hey\s+)?(?:lumina|λουμινα)\s*/i,'').trim();
function ui(){const b=$('#navHandsFreeBtn');if(b){b.setAttribute('aria-pressed',String(enabled));b.title=enabled?'Hands-free LUMINA ενεργό':'Hands-free LUMINA ανενεργό';const small=b.querySelector('small');if(small)small.textContent=enabled?'LUMINA ON':'Hands-free';const span=b.querySelector('span');if(span)span.textContent=enabled?'🟢':'🔊'}const h=$('#voiceHint');if(h&&enabled)h.textContent='Hands-free ενεργό — απαντώ μόνο όταν η πρόταση ξεκινά με «LUMINA».'}
function stop(){clearTimeout(resumeTimer);if(running&&recognition)try{recognition.stop()}catch{}}
function start(isManual=false){if(!recognition||running||document.visibilityState!=='visible'||(!enabled&&!isManual))return;manual=isManual;try{recognition.start()}catch{}}
function resume(ms=650){clearTimeout(resumeTimer);if(enabled)resumeTimer=setTimeout(()=>start(false),ms)}
function speak(text){if(!text||!('speechSynthesis'in window))return;ignoreUntil=Date.now()+Math.max(2500,text.length*55);stop();const u=new SpeechSynthesisUtterance(text);u.lang='el-GR';u.rate=.96;u.onend=()=>resume(500);u.onerror=()=>resume(500);speechSynthesis.cancel();speechSynthesis.speak(u)}
async function gps(){try{const p=window.LuminaGPS?.getLastFix?.(60000)||window.LuminaGPS?.lastFix;if(Number.isFinite(+p?.lat)&&Number.isFinite(+p?.lng))return{lat:+p.lat,lng:+p.lng}}catch{}try{const p=window.__luminaCurrentUserMarker?.getLatLng?.();if(Number.isFinite(+p?.lat)&&Number.isFinite(+p?.lng))return{lat:+p.lat,lng:+p.lng}}catch{}return new Promise((resolve,reject)=>navigator.geolocation?.getCurrentPosition(p=>resolve({lat:p.coords.latitude,lng:p.coords.longitude}),reject,{enableHighAccuracy:true,timeout:6000,maximumAge:30000})||reject(new Error('gps')))}
function query(type,o,radius){const clauses=[];for(const[k,v]of TYPES[type].tags)for(const kind of ['node','way','relation'])clauses.push(`${kind}(around:${radius},${o.lat},${o.lng})[\"${k}\"=\"${v}\"];`);return`[out:json][timeout:8];(${clauses.join('')});out center tags 40;`}
async function request(ep,q){const c=new AbortController(),t=setTimeout(()=>c.abort(),7000);try{const r=await fetch(`${ep}?data=${encodeURIComponent(q)}`,{signal:c.signal,cache:'no-store',headers:{Accept:'application/json'}});if(!r.ok)throw new Error(String(r.status));return r.json()}finally{clearTimeout(t)}}
function points(d,o){const out=[];for(const x of d.elements||[]){const lat=Number(x.lat??x.center?.lat),lng=Number(x.lon??x.center?.lon);if(!Number.isFinite(lat)||!Number.isFinite(lng))continue;const name=x.tags?.['name:el']||x.tags?.name||x.tags?.brand||x.tags?.operator;if(!name)continue;const p={lat,lng},distance=dist(o,p);out.push({name,p,distance})}return out}
async function nearest(type){const o=await gps();for(const radius of [1500,3000,6000,10000]){const q=query(type,o,radius);const settled=await Promise.allSettled(ENDPOINTS.map(ep=>request(ep,q)));const merged=[];for(const s of settled)if(s.status==='fulfilled')merged.push(...points(s.value,o));merged.sort((a,b)=>a.distance-b.distance);const uniq=[];for(const x of merged){if(!uniq.some(y=>dist(x.p,y.p)<45||y.name.toLocaleLowerCase('el-GR')===x.name.toLocaleLowerCase('el-GR')&&dist(x.p,y.p)<150))uniq.push(x)}if(uniq.length)return uniq[0]}return null}
function prepareRoute(x){const b=document.createElement('button');b.className='poi-route';b.dataset.lat=String(x.p.lat);b.dataset.lng=String(x.p.lng);b.dataset.name=x.name;b.hidden=true;document.body.appendChild(b);b.click();setTimeout(()=>b.remove(),0)}
async function answerNearest(type){const label=TYPES[type]?.label||'σημείο';speak(`Ψάχνω το κοντινότερο ${label}.`);try{const x=await nearest(type);if(!x)return speak(`Δεν βρήκα καταχωρημένο ${label} κοντά σου.`);prepareRoute(x);speak(`Το κοντινότερο ${label} είναι ${x.name}, περίπου ${fmt(x.distance)} από τη θέση σου. Ετοίμασα τη διαδρομή στην οθόνη.`)}catch{ speak(`Δεν μπόρεσα να ελέγξω τώρα τα κοντινά ${label}. Δοκίμασε ξανά σε λίγο.`)}}
function command(raw){const t=norm(raw);if(!t)return;if(/βενζ|καυσιμ|fuel/.test(t))return answerNearest('fuel');if(/φαρμακ/.test(t))return answerNearest('pharmacy');if(/καφε|coffee/.test(t))return answerNearest('cafe');if(/εστια|ταβερ|φαγη|σουβλα/.test(t))return answerNearest('restaurant');if(/νοσοκο/.test(t))return answerNearest('hospital');if(/παρκιν|parking/.test(t))return answerNearest('parking');if(/σταματα|τελος διαδρομ/.test(t)){document.querySelector('#navStopBtn')?.click();return speak('Σταματώ την πλοήγηση.')}if(/που ειμαι|θεση μου|τοποθεσια μου/.test(t))return speak('Η θέση σου εμφανίζεται στον χάρτη με βάση το ενεργό GPS.');const input=$('#destinationInput');if(input&&t){const q=t.replace(/^(πες μου|βρες μου|πηγαινε με|πηγαινε|οδηγησε με|διαδρομη για|οδηγιες για)\s+/,'').trim();if(q){input.value=q;$('#routeBtn')?.click();speak(`Αναζητώ ${q}.`)}}}
function disableLegacyHandsFree(){const b=$('#handsFreeBtn');if(b&&/ON/i.test(b.textContent||''))try{b.click()}catch{}}
function toggle(){enabled=!enabled;localStorage.setItem('lumina-strict-handsfree',enabled?'1':'0');disableLegacyHandsFree();ui();if(enabled){speak('Hands-free LUMINA ενεργό. Θα απαντώ μόνο όταν ξεκινάς την πρόταση με LUMINA.')}else{stop();speak('Hands-free LUMINA ανενεργό.')}}
function setup(){if(!SR){ui();return}recognition=new SR();recognition.lang='el-GR';recognition.interimResults=false;recognition.maxAlternatives=1;recognition.continuous=false;recognition.onstart=()=>{running=true};recognition.onend=()=>{running=false;manual=false;resume()};recognition.onerror=()=>{running=false;resume(900)};recognition.onresult=e=>{if(Date.now()<ignoreUntil||speechSynthesis?.speaking)return;const text=e.results?.[0]?.[0]?.transcript||'';if(manual)return command(text);if(!enabled||!startsWithWake(text))return;const cmd=stripWake(text);if(cmd)command(cmd)};enabled=localStorage.getItem('lumina-strict-handsfree')==='1';disableLegacyHandsFree();ui();if(enabled)resume(700)}
document.addEventListener('click',e=>{const hands=e.target.closest?.('#navHandsFreeBtn');if(hands){e.preventDefault();e.stopImmediatePropagation();toggle();return}const voice=e.target.closest?.('#navVoiceBtn');if(voice){e.preventDefault();e.stopImmediatePropagation();start(true)}},true);
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')resume(400);else stop()});
window.addEventListener('load',setup,{once:true});
window.LuminaStrictVoice={get enabled(){return enabled},toggle,startsWithWake,stripWake};
})();