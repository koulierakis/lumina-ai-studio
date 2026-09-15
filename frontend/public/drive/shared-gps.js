(()=>{
  'use strict';
  const MAX_AGE_MS=30000;
  const api=window.LuminaGPS=window.LuminaGPS||{lastFix:null};
  function save(position,source='geolocation'){
    if(!position?.coords)return null;
    const lat=Number(position.coords.latitude),lng=Number(position.coords.longitude);
    if(!Number.isFinite(lat)||!Number.isFinite(lng))return null;
    const fix={lat,lng,accuracy:Number(position.coords.accuracy)||null,speed:Number.isFinite(Number(position.coords.speed))?Number(position.coords.speed):null,heading:Number.isFinite(Number(position.coords.heading))?Number(position.coords.heading):null,timestamp:Number(position.timestamp)||Date.now(),receivedAt:Date.now(),source};
    api.lastFix=fix;
    window.dispatchEvent(new CustomEvent('lumina-gps-fix',{detail:fix}));
    return fix;
  }
  api.getLastFix=(maxAge=MAX_AGE_MS)=>{
    const fix=api.lastFix;
    if(!fix)return null;
    const age=Date.now()-(fix.receivedAt||fix.timestamp||0);
    return age<=maxAge?fix:null;
  };
  api.getPosition=(opts={})=>{
    const maxAge=Number.isFinite(opts.maxAge)?opts.maxAge:MAX_AGE_MS;
    const cached=api.getLastFix(maxAge);
    if(cached)return Promise.resolve({...cached,source:'shared-cache'});
    return new Promise((resolve,reject)=>{
      if(!navigator.geolocation)return reject(Object.assign(new Error('Geolocation unavailable'),{kind:'gps-unavailable'}));
      navigator.geolocation.getCurrentPosition(p=>resolve(save(p,'direct')),reject,{enableHighAccuracy:true,maximumAge:maxAge,timeout:opts.timeout||7000});
    });
  };
  if(navigator.geolocation&&!navigator.geolocation.__luminaWrapped){
    const geo=navigator.geolocation;
    const originalWatch=geo.watchPosition.bind(geo);
    const originalGet=geo.getCurrentPosition.bind(geo);
    try{
      geo.watchPosition=function(success,error,options){return originalWatch(p=>{save(p,'watch');success?.(p)},error,options)};
      geo.getCurrentPosition=function(success,error,options){return originalGet(p=>{save(p,'current');success?.(p)},error,options)};
      geo.__luminaWrapped=true;
    }catch{}
  }
})();
