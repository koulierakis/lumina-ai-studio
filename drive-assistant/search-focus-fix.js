(()=>{
'use strict';
const $=s=>document.querySelector(s);
const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('el-GR').replace(/[^a-z0-9α-ω]+/gi,' ').trim();
const ignored=new Set(['ο','η','το','τα','της','του','των','σε','στη','στην','στο','και','greece','ελλαδα','ελλαδας','fitness','boutique','store','shop','gym','center','centre','καταστημα','γυμναστηριο','κεντρο']);
const localDirectory=[
 {name:'ATHLETICO Wellness & Fitness Center',aliases:['athletico','αθλετικο'],city:['τρικαλα','trikala'],address:'Εθνικής Αντιστάσεως 21, Τρίκαλα',source:'Τοπικός κατάλογος LUMINA'},
 {name:'Aeton Melathron Hotel',aliases:['μελαθρον','melathron','aeton melathron','αετων μελαθρον'],city:['τρικαλα','trikala'],address:'Νεάρχου & Νίκης, Τρίκαλα 421 31',source:'Τοπικός κατάλογος LUMINA'},
 {name:'Aeton Melathron Events',aliases:['μελαθρον','melathron','aeton melathron','αετων μελαθρον'],city:['τρικαλα','trikala'],address:'4ο χλμ Τρικάλων - Μεγαλοχωρίου, Τρίκαλα',source:'Τοπικός κατάλογος LUMINA'}
];
function queryTokens(){const q=norm($('#destinationInput')?.value||'');return q.split(' ').filter(t=>t.length>1&&!ignored.has(t))}
function strictMatch(text,tokens){if(tokens.length<2)return true;const n=norm(text);return tokens.every(t=>n.includes(t))}
function directoryMatches(q){const n=norm(q);return localDirectory.filter(p=>p.aliases.some(a=>n.includes(norm(a)))&&(!p.city.length||p.city.some(c=>n.includes(norm(c)))))}
function escapeHtml(s=''){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function addDirectoryCards(panel,q){const matches=directoryMatches(q);if(!matches.length)return;
 const wrap=document.createElement('div');wrap.className='lumina-directory-results';
 wrap.innerHTML=matches.map((p,i)=>`<article class="name-search-card lumina-directory-card"><button type="button" class="name-search-main" data-lumina-directory="${i}"><strong>${escapeHtml(p.name)}</strong><span><b>Οδός / τοποθεσία:</b> ${escapeHtml(p.address)}</span><span><b>Πηγή:</b> ${escapeHtml(p.source)}</span></button><button type="button" class="name-search-start" data-lumina-directory-start="${i}">▶ Έναρξη</button></article>`).join('');
 panel.prepend(wrap);
 wrap.addEventListener('click',e=>{const b=e.target.closest('[data-lumina-directory],[data-lumina-directory-start]');if(!b)return;const i=Number(b.dataset.luminaDirectory??b.dataset.luminaDirectoryStart),p=matches[i];if(!p)return;routeDirectoryPlace(p,Boolean(b.dataset.luminaDirectoryStart!==undefined));});
}
function routeDirectoryPlace(p,start){const input=$('#destinationInput'),btn=$('#routeBtn');if(!input||!btn)return;input.value=p.address;input.dispatchEvent(new Event('input',{bubbles:true}));btn.click();if(!start)return;let tries=0;const timer=setInterval(()=>{tries++;const panel=$('#nameSearchResults');const startBtn=panel?.querySelector('.name-search-card:not(.lumina-directory-card) .name-search-start:not([disabled])');if(startBtn){clearInterval(timer);startBtn.click()}else if(tries>20)clearInterval(timer)},250)}
function apply(){const panel=$('#nameSearchResults'),input=$('#destinationInput');if(!panel||!input||panel.classList.contains('hidden'))return;const q=input.value,tokens=queryTokens();
 panel.querySelectorAll('.lumina-directory-results').forEach(x=>x.remove());
 const cards=[...panel.querySelectorAll(':scope > .name-search-card')];
 let visible=0;
 for(const card of cards){const ok=strictMatch(card.innerText,tokens);card.style.display=ok?'':'none';if(ok)visible++}
 if(tokens.length>=2)addDirectoryCards(panel,q);
 const directoryCount=panel.querySelectorAll('.lumina-directory-card').length;
 if(tokens.length>=2&&visible===0&&directoryCount===0){let empty=panel.querySelector('.lumina-strict-empty');if(!empty){empty=document.createElement('div');empty.className='name-search-empty lumina-strict-empty';panel.prepend(empty)}empty.textContent=`Δεν βρέθηκε αποτέλεσμα που να ταιριάζει ταυτόχρονα με «${q}». Δεν εμφανίζονται αποτελέσματα από άλλη πόλη.`}else panel.querySelector('.lumina-strict-empty')?.remove();
 panel.scrollTop=0;
}
function watch(){const input=$('#destinationInput');if(!input)return;let panel=$('#nameSearchResults');if(!panel){const observer=new MutationObserver(()=>{panel=$('#nameSearchResults');if(panel){observer.disconnect();watchPanel(panel)}});observer.observe(document.body,{childList:true,subtree:true})}else watchPanel(panel);input.addEventListener('input',()=>setTimeout(apply,650));$('#routeBtn')?.addEventListener('click',()=>setTimeout(apply,900),true)}
function watchPanel(panel){let busy=false;new MutationObserver(()=>{if(busy)return;busy=true;setTimeout(()=>{apply();busy=false},60)}).observe(panel,{childList:true,subtree:true});setTimeout(apply,100)}
window.addEventListener('DOMContentLoaded',watch);
})();
