
import React from "react";
import {
    Search,
    X,
    Filter
} from "lucide-react";

export default function SearchFilters({

    filters,

    updateFilter,

    categories=[],

    folders=[],

    tags=[],

    countries=[],

    languages=[],

    resetFilters

}){

return(

<div className="rounded-2xl border border-white/10 bg-white/5 p-5">

<div className="flex items-center gap-2 mb-5">

<Filter size={18}/>

<h3 className="font-semibold">

Search & Filters

</h3>

</div>

<div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">

<div>

<label className="mb-2 block text-xs opacity-70">

Αναζήτηση

</label>

<div className="relative">

<Search
size={16}
className="absolute left-3 top-3 opacity-50"
/>

<input

className="field w-full pl-10"

placeholder="Τίτλος, περιγραφή..."

value={filters.text||""}

onChange={e=>
updateFilter(
"text",
e.target.value
)
}

/>

</div>

</div>

<div>

<label className="mb-2 block text-xs opacity-70">

Κατηγορία

</label>

<select

className="field w-full"

value={filters.category||""}

onChange={e=>
updateFilter(
"category",
e.target.value
)
}

>

<option value="">

Όλες

</option>

{categories.map(c=>

<option
key={c.id||c.name}
value={c.name}
>

{c.name}

</option>

)}

</select>

</div>

<div>

<label className="mb-2 block text-xs opacity-70">

Φάκελος

</label>

<select

className="field w-full"

value={filters.folder_id||""}

onChange={e=>
updateFilter(
"folder_id",
e.target.value
)
}

>

<option value="">

Όλοι

</option>

{folders.map(f=>

<option
key={f.id}
value={f.id}
>

{f.name}

</option>

)}

</select>

</div>

<div>

<label className="mb-2 block text-xs opacity-70">

Χώρα

</label>

<select

className="field w-full"

value={filters.country||"ALL"}

onChange={e=>
updateFilter(
"country",
e.target.value
)
}

>

<option value="ALL">

Όλες

</option>

{countries.map(c=>

<option
key={c.code||c}
value={c.code||c}
>

{c.label||c}

</option>

)}

</select>

</div>

<div>

<label className="mb-2 block text-xs opacity-70">

Γλώσσα

</label>

<select

className="field w-full"

value={filters.language||"ALL"}

onChange={e=>
updateFilter(
"language",
e.target.value
)
}

>

<option value="ALL">

Όλες

</option>

{languages.map(l=>

<option
key={l.code||l}
value={l.code||l}
>

{l.label||l}

</option>

)}

</select>

</div>

<div>

<label className="mb-2 block text-xs opacity-70">

Tag

</label>

<select

className="field w-full"

value={filters.tag||""}

onChange={e=>
updateFilter(
"tag",
e.target.value
)
}

>

<option value="">

Όλα

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

</div>

</div>

<div className="mt-5 flex justify-end">

<button

className="btn secondary"

onClick={resetFilters}

>

<X
size={16}
className="mr-2"
/>

Καθαρισμός φίλτρων

</button>

</div>

</div>

);

}
