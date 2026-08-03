
import React from "react";
import {
Eye,
Download,
Copy,
FolderOpen,
Trash2,
Pencil,
X
} from "lucide-react";

export default function DocumentContextMenu({

open,

x=0,

y=0,

document,

onClose,

onPreview,

onDownload,

onDuplicate,

onMove,

onRename,

onDelete

}){

if(!open||!document)
return null;

const Item=({
icon:Icon,
label,
danger,
action
})=>(

<button

className={`
w-full
flex
items-center
gap-3
px-4
py-3
text-left
transition

${danger
?
"text-red-400 hover:bg-red-500/10"
:
"hover:bg-white/10"
}

`}

onClick={()=>{
action(document);
onClose?.();
}}

>

<Icon size={16}/>

{label}

</button>

);

return(

<>

<div

className="fixed inset-0 z-[9998]"

onClick={onClose}

/>

<div

className="
fixed
z-[9999]
w-64
overflow-hidden
rounded-2xl
border
border-white/10
bg-zinc-900
shadow-2xl
"

style={{
left:x,
top:y
}}

>

<div className="border-b border-white/10 p-4 font-semibold">

{document.title}

</div>

<Item
icon={Eye}
label="Προεπισκόπηση"
action={onPreview}
/>

<Item
icon={Download}
label="Download"
action={onDownload}
/>

<Item
icon={Copy}
label="Duplicate"
action={onDuplicate}
/>

<Item
icon={FolderOpen}
label="Move"
action={onMove}
/>

<Item
icon={Pencil}
label="Rename"
action={onRename}
/>

<Item
icon={Trash2}
label="Delete"
danger
action={onDelete}
/>

<div className="border-t border-white/10">

<button

className="
w-full
flex
items-center
gap-3
px-4
py-3
hover:bg-white/10
"

onClick={onClose}

>

<X size={16}/>

Close

</button>

</div>

</div>

</>

);

}
