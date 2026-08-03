
import React from "react";
import {
ChevronLeft,
ChevronRight
} from "lucide-react";

export default function Pagination({

page=1,

pageSize=24,

total=0,

setPage,

setPageSize

}){

const totalPages=Math.max(
1,
Math.ceil(total/pageSize)
);

return(

<div
className="
mt-6
flex
flex-wrap
items-center
justify-between
gap-4
rounded-2xl
border
border-white/10
bg-white/5
p-4
"
>

<div className="text-sm opacity-70">

{total} έγγραφα

</div>

<div className="flex items-center gap-2">

<button
className="btn secondary"
disabled={page<=1}
onClick={()=>setPage(page-1)}
>

<ChevronLeft size={16}/>

</button>

<div className="px-4">

{page} / {totalPages}

</div>

<button
className="btn secondary"
disabled={page>=totalPages}
onClick={()=>setPage(page+1)}
>

<ChevronRight size={16}/>

</button>

</div>

<select

className="field w-28"

value={pageSize}

onChange={e=>
setPageSize(
Number(e.target.value)
)
}

>

<option value={12}>12</option>
<option value={24}>24</option>
<option value={48}>48</option>
<option value={96}>96</option>

</select>

</div>

);

}
