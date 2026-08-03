
import React from "react";
import {
    Search,
    Grid2X2,
    List,
    RefreshCw,
    Globe,
    Languages
} from "lucide-react";

export default function DocumentToolbar({

    filters,
    updateFilter,

    tags=[],

    countries=[],

    languages=[],

    viewMode,

    setViewMode,

    refresh,

    uiLanguage,

    setUiLanguage

}){

return(

<div className="mb-5 rounded-2xl border border-white/10 bg-white/5 p-4">

<div className="flex flex-wrap items-center gap-3">

<input
className="field flex-1 min-w-[280px]"
placeholder="Αναζήτηση..."
value={filters.text||""}
onChange={e=>updateFilter("text",e.target.value)}
/>

<select
className="field"
value={filters.country||"ALL"}
onChange={e=>updateFilter("country",e.target.value)}
>

<option value="ALL">🌍 Όλες οι χώρες</option>

{countries.map(c=>

<option
key={c.code||c}
value={c.code||c}
>

{c.label||c}

</option>

)}

</select>

<select
className="field"
value={filters.language||"ALL"}
onChange={e=>updateFilter("language",e.target.value)}
>

<option value="ALL">Όλες οι γλώσσες</option>

{languages.map(l=>

<option
key={l.code||l}
value={l.code||l}
>

{l.label||l}

</option>

)}

</select>

<select
className="field"
value={filters.tag||""}
onChange={e=>updateFilter("tag",e.target.value)}
>

<option value="">
Όλα τα Tags
</option>

{tags.map(tag=>

<option
key={tag.id||tag.name}
value={tag.name}
>

{tag.name}

</option>

)}

</select>

<button
className="btn"
onClick={refresh}
>

<RefreshCw
size={16}
/>

</button>

<button
className={
viewMode==="grid"
?
"btn"
:
"btn secondary"
}
onClick={()=>setViewMode("grid")}
>

<Grid2X2
size={16}
/>

</button>

<button
className={
viewMode==="list"
?
"btn"
:
"btn secondary"
}
onClick={()=>setViewMode("list")}
>

<List
size={16}
/>

</button>

<button
className="btn secondary"
onClick={()=>
setUiLanguage(
uiLanguage==="el"
?
"en"
:
"el"
)
}
>

<Languages
size={16}
/>

{uiLanguage.toUpperCase()}

</button>

</div>

</div>

);

}
