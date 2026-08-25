
const API_BASE_URL =
process.env.REACT_APP_API_URL ||
"";

async function request(endpoint,options={}){

const response=await fetch(
API_BASE_URL+endpoint,
{
headers:{
Accept:"application/json",
"Content-Type":"application/json",
...(options.headers||{})
},
...options
}
);

if(!response.ok){

let message=`HTTP ${response.status}`;

try{

const body=await response.json();

message=
body.detail||
body.message||
message;

}catch{}

throw new Error(message);

}

if(response.status===204)
return null;

return response.json();

}

export const DocumentApi={

search(params={}){

const query=new URLSearchParams();

Object.entries(params).forEach(([k,v])=>{

if(
v!==undefined &&
v!==null &&
v!=="" &&
v!=="ALL"
){

query.set(k,String(v));

}

});

return request(
"/api/documents/search?"+query.toString()
);

},

get(id){

return request(
`/api/documents/${id}`
);

},

categories(){

return request(
"/api/documents/categories"
);

},

folders(){

return request(
"/api/documents/folders"
);

},

tags(){

return request(
"/api/documents/tags"
);

},

createFolder(payload){

return request(
"/api/documents/folders",
{
method:"POST",
body:JSON.stringify(payload)
}
);

},

renameFolder(id,name){

return request(
`/api/documents/folders/${id}`,
{
method:"PUT",
body:JSON.stringify({
name
})
}
);

},

deleteFolder(id){

return request(
`/api/documents/folders/${id}`,
{
method:"DELETE"
}
);

},

moveFolder(id,parent_id){

return request(
`/api/documents/folders/${id}/move`,
{
method:"POST",
body:JSON.stringify({
parent_id
})
}
);

},

download(id){

window.open(
API_BASE_URL+
`/api/documents/${id}/download`,
"_blank"
);

}

};

export default DocumentApi;
