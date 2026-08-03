
import React from "react";
import {
    FileText,
    Globe,
    Languages,
    Tag,
    Calendar
} from "lucide-react";

export default function DocumentGrid({

    documents=[],
    loading=false,
    onSelect=()=>{},
    selectedId=null

}){

if(loading){

return(

<div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">

{Array.from({length:9}).map((_,i)=>

<div
key={i}
className="h-64 rounded-2xl animate-pulse bg-white/5"
/>

)}

</div>

);

}

if(!documents.length){

return(

<div className="rounded-2xl border border-dashed border-white/10 p-12 text-center">

<FileText
size={44}
className="mx-auto mb-4 opacity-40"
/>

<div className="text-xl">
Δεν βρέθηκαν έγγραφα
</div>

</div>

);

}

return(

<div
className="
grid
grid-cols-1
md:grid-cols-2
xl:grid-cols-3
2xl:grid-cols-4
gap-5
"
>

{documents.map(doc=>(

<button

key={doc.id}

type="button"

onClick={()=>onSelect(doc)}

className={`
rounded-2xl
border
p-5
text-left
transition
hover:scale-[1.02]
hover:border-yellow-500

${selectedId===doc.id
?
"border-yellow-500 bg-yellow-500/10"
:
"border-white/10 bg-white/5"
}

`}

>

<div className="flex items-start justify-between">

<div>

<div className="font-semibold">

{doc.title}

</div>

<div className="mt-1 text-xs opacity-60">

{doc.category||"General"}

</div>

</div>

<FileText size={20}/>

</div>

<div className="mt-4 line-clamp-5 text-sm opacity-70">

{doc.summary||
doc.description||
doc.content_plain||
""}

</div>

<div className="mt-5 flex flex-wrap gap-2">

{(doc.tags||[]).map(tag=>

<div

key={tag}

className="
rounded-full
bg-yellow-500/10
border
border-yellow-500/20
px-2
py-1
text-[11px]
"

>

<Tag
size={11}
className="inline mr-1"
/>

{tag}

</div>

)}

</div>

<div className="mt-5 flex flex-wrap gap-3 text-xs opacity-60">

<div className="flex items-center gap-1">

<Globe size={13}/>

{doc.country||"GR"}

</div>

<div className="flex items-center gap-1">

<Languages size={13}/>

{doc.language||"EL"}

</div>

{doc.updated_at&&(

<div className="flex items-center gap-1">

<Calendar size={13}/>

{doc.updated_at}

</div>

)}

</div>

</button>

))}

</div>

);

}
