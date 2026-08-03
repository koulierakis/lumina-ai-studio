
import React from "react";
import {
    FileText,
    Download,
    Printer,
    ExternalLink,
    Globe,
    Languages,
    Tag,
    Calendar
} from "lucide-react";

export default function PreviewPane({

    document,

    onDownload=()=>{},

    onPrint=()=>{},

    onOpen=()=>{}

}){

if(!document){

return(

<div
className="
h-full
rounded-2xl
border
border-white/10
bg-white/5
flex
items-center
justify-center
p-10
"
>

<div className="text-center">

<FileText
size={54}
className="mx-auto mb-5 opacity-40"
/>

<h3 className="text-xl font-semibold">

Επιλέξτε ένα έγγραφο

</h3>

<p className="mt-3 opacity-60">

Η προεπισκόπηση θα εμφανιστεί εδώ.

</p>

</div>

</div>

);

}

return(

<div
className="
flex
flex-col
h-full
rounded-2xl
border
border-white/10
bg-white/5
overflow-hidden
"
>

<div
className="
flex
items-center
justify-between
border-b
border-white/10
px-5
py-4
"
>

<div>

<h2 className="font-semibold text-lg">

{document.title}

</h2>

<div className="mt-1 text-xs opacity-60">

{document.category||"General"}

</div>

</div>

<div className="flex gap-2">

<button
className="btn secondary"
onClick={()=>onDownload(document)}
>

<Download size={16}/>

</button>

<button
className="btn secondary"
onClick={()=>onPrint(document)}
>

<Printer size={16}/>

</button>

<button
className="btn"
onClick={()=>onOpen(document)}
>

<ExternalLink size={16}/>

</button>

</div>

</div>

<div className="px-5 py-3 flex flex-wrap gap-4 text-xs opacity-70">

<div className="flex items-center gap-1">

<Globe size={13}/>

{document.country||"GR"}

</div>

<div className="flex items-center gap-1">

<Languages size={13}/>

{document.language||"EL"}

</div>

{document.updated_at&&(

<div className="flex items-center gap-1">

<Calendar size={13}/>

{document.updated_at}

</div>

)}

</div>

{document.tags?.length>0&&(

<div className="px-5 pb-4 flex flex-wrap gap-2">

{document.tags.map(tag=>(

<div

key={tag}

className="
rounded-full
border
border-yellow-500/20
bg-yellow-500/10
px-3
py-1
text-xs
"

>

<Tag
size={11}
className="inline mr-1"
/>

{tag}

</div>

))}

</div>

)}

<div
className="
flex-1
overflow-auto
bg-zinc-950
p-6
"
>

{document.preview_url ? (

<iframe

title="preview"

src={document.preview_url}

className="
w-full
h-full
rounded-xl
bg-white
"

>

</iframe>

):(

<div
className="
rounded-xl
bg-white
text-black
mx-auto
max-w-[850px]
min-h-full
p-10
shadow-2xl
"
>

<pre
className="
whitespace-pre-wrap
font-sans
text-[15px]
leading-7
"
>

{document.content||
document.content_plain||
document.summary||
"Δεν υπάρχει διαθέσιμη προεπισκόπηση."}

</pre>

</div>

)}

</div>

</div>

);

}
