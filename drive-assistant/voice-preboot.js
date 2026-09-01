(()=>{
'use strict';
try{
  const key='lumina-drive-session-v1';
  const raw=localStorage.getItem(key);
  if(raw){
    const s=JSON.parse(raw);
    if(s&&typeof s==='object'){
      s.handsFree=false;
      localStorage.setItem(key,JSON.stringify(s));
    }
  }
}catch{}
window.__LUMINA_STRICT_VOICE_BOOT__=true;
})();
