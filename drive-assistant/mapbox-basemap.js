(()=>{
'use strict';
const token=()=>String(window.__LUMINA_CONFIG__?.mapboxAccessToken||'').trim();
function mount(){
  const map=window.__luminaDriveMap;
  const key=token();
  if(!map||!window.L||!key){setTimeout(mount,300);return}
  if(map.__luminaMapboxBasemap)return;
  map.__luminaMapboxBasemap=true;
  try{
    for(const layer of Object.values(map._layers||{})){
      if(layer instanceof L.TileLayer)map.removeLayer(layer);
    }
    const url=`https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/512/{z}/{x}/{y}@2x?access_token=${encodeURIComponent(key)}`;
    const base=L.tileLayer(url,{tileSize:512,zoomOffset:-1,maxZoom:20,attribution:'© Mapbox © OpenStreetMap',crossOrigin:true});
    base.addTo(map);
    base.bringToBack();
  }catch(e){console.warn('[LUMINA Mapbox basemap]',e)}
}
mount();
})();
