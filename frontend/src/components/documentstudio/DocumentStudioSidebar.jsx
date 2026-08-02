import React,{useMemo,useState} from "react";
import {
  FileText,
  FolderPlus,
  Search,
} from "lucide-react";

import {
  documentStats,
  summarizeDocument,
} from "../../documents/model";


export default function DocumentStudioSidebar({

  filters,
  setFilters,
  categories,
  folders,
  documents,
  loading,
  selectedDocument,
  onSearch,
  onCreateFolder,
  renameFolder,
  deleteFolder,
  moveFolder,
  onSelectDocument,
  selectedIds = [],
  onToggleSelected,
}) {


  const [expanded,setExpanded]=useState({});
const [newFolderName,setNewFolderName]=useState("");
const [showNewFolder,setShowNewFolder]=useState(false);

const [editingFolderId,setEditingFolderId]=useState(null);
const [editingFolderName,setEditingFolderName]=useState("");

const [contextFolder,setContextFolder]=useState(null);
const [contextPos,setContextPos]=useState({x:0,y:0});

const [folderSearch,setFolderSearch]=useState("");

const [sortFolders,setSortFolders]=useState("name");

const [collapsedSidebar,setCollapsedSidebar]=useState(false);

const [showStats,setShowStats]=useState(true);

  const toggleFolder=id=>{
      setExpanded(p=>({
          ...p,
          [id]:!p[id]
      }));
  };

  const roots=useMemo(
      ()=>folders.filter(f=>!f.parent_id),
      [folders]
  );
  const sortedFolders=useMemo(()=>{

      const timestamp=folder=>Date.parse(folder.created_at||folder.updated_at||"")||0;

      return [...folders].sort((a,b)=>{

          if(sortFolders==="oldest") return timestamp(a)-timestamp(b);

          if(sortFolders==="newest") return timestamp(b)-timestamp(a);

          return String(a.name||"").localeCompare(String(b.name||""));

      });

  },[folders,sortFolders]);

  function renderTree(parent=null,level=0){

      return sortedFolders
.filter(f=>{

if(f.parent_id!==parent)
return false

if(
!folderSearch.trim()
)
return true

return f.name
.toLowerCase()
.includes(
folderSearch
.toLowerCase()
)

})
          .map(folder=>{

              const open=expanded[folder.id]!==false;

              return(
                  <React.Fragment key={folder.id}>

                      <button
                          type="button"

                          onContextMenu={(e)=>{

                              e.preventDefault();

                              setContextFolder(folder);

                              setContextPos({
                                  x:e.clientX,
                                  y:e.clientY
                              });

                          }}

                          onClick={()=>toggleFolder(folder.id)}
                          className="flex w-full items-center gap-2 rounded-xl px-2 py-2 text-left hover:bg-white/5"
                          style={{paddingLeft:12+level*18}}
                      >

                          <span>
                              {open?"📂":"📁"}
                          </span>


{
editingFolderId===folder.id?

<input
className="field flex-1"
value={editingFolderName}
onChange={e=>setEditingFolderName(e.target.value)}
onBlur={()=>{
renameFolder?.(folder.id,editingFolderName);
setEditingFolderId(null);
}}
onKeyDown={e=>{
if(e.key==="Enter"){
renameFolder?.(folder.id,editingFolderName);
setEditingFolderId(null);
}
}}
autoFocus
/>

:

<span
className="flex-1"
onDoubleClick={()=>{
setEditingFolderId(folder.id);
setEditingFolderName(folder.name);
}}
>
{folder.name}
</span>

}


                      </button>

                      {open && renderTree(folder.id,level+1)}

                  </React.Fragment>
              );

          });

  }


  return (

    <>

    <button
        className="mb-3 rounded-xl border border-white/10 px-3 py-2 hover:bg-white/10"
        onClick={()=>
            setCollapsedSidebar(v=>!v)
        }
    >
        {collapsedSidebar ? "▶ Άνοιγμα Sidebar" : "◀ Απόκρυψη Sidebar"}
    </button>

    {!collapsedSidebar && (
    <aside className="space-y-4">
      <section className="rounded-3xl border border-white/10 bg-white/[0.045] p-5 shadow-xl backdrop-blur-sm">
        <div className="mb-4 flex items-center gap-3">
          <Search className="h-5 w-5 shrink-0 text-gold" />

          <h2 className="font-display text-xl leading-tight">
            Βιβλιοθήκη Εγγράφων
          </h2>
        </div>

        <div className="space-y-3">
          <input
            className="field"
            placeholder="Αναζήτηση σε τίτλο, περιεχόμενο και tags"
            value={filters.q || ""}
            onChange={(event) =>
              setFilters((current) => ({
                ...current,
                q: event.target.value,
              }))
            }
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                onSearch();
              }
            }}
          />

          <div className="grid grid-cols-2 gap-2">
            <select
              className="field"
              value={filters.category || ""}
              onChange={(event) =>
                setFilters((current) => ({
                  ...current,
                  category: event.target.value,
                }))
              }
            >
              <option value="">Όλες οι κατηγορίες</option>

              {categories.map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>

            <select
              className="field"
              value={filters.folder_id || ""}
              onChange={(event) =>
                setFilters((current) => ({
                  ...current,
                  folder_id: event.target.value,
                }))
              }
            >
              <option value="">Όλοι οι φάκελοι</option>

              {folders.map((folder) => (
                <option key={folder.id} value={folder.id}>
                  {folder.name}
                </option>
              ))}
            </select>
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              className="btn"
              onClick={onSearch}
            >
              <Search className="h-4 w-4" />
              Αναζήτηση
            </button>

            <button
              type="button"
              className="btn secondary"
              onClick={()=>setShowNewFolder(true)}
            >
              <FolderPlus className="h-4 w-4" />
              Νέος φάκελος
            </button>
          </div>
        </div>
      </section>




      {showNewFolder && (

        <div className="rounded-xl border border-gold/20 bg-black/60 p-3 mb-3">

            <input
                className="field w-full"
                placeholder="Όνομα φακέλου..."
                value={newFolderName}
                onChange={e=>setNewFolderName(e.target.value)}
            />

            <div className="mt-3 flex gap-2">

                <button
                    className="btn"
                    onClick={()=>{
                        if(!newFolderName.trim()) return;

                        onCreateFolder?.({
                            name:newFolderName
                        });

                        setNewFolderName("");
                        setShowNewFolder(false);

                    }}
                >
                    Δημιουργία
                </button>

                <button
                    className="btn secondary"
                    onClick={()=>{
                        setShowNewFolder(false);
                    }}
                >
                    Άκυρο
                </button>

            </div>

        </div>

      )}

      <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">


          <select
              className="field mb-3 w-full"
              value={sortFolders}
              onChange={e=>setSortFolders(e.target.value)}
          >
              <option value="name">
                  Ταξινόμηση: Όνομα
              </option>

              <option value="newest">
                  Νεότεροι
              </option>

              <option value="oldest">
                  Παλαιότεροι
              </option>

          </select>

          <input
              className="field mb-3 w-full"
              placeholder="Αναζήτηση φακέλου..."
              value={folderSearch}
              onChange={e=>setFolderSearch(e.target.value)}
          />

          <div className="mb-3 text-xs uppercase tracking-[0.2em] text-white/50">
              Folder Tree · {roots.length} root folder{roots.length === 1 ? '' : 's'}
          </div>

          {renderTree()}

      </section>

      {contextFolder && (

        <div
          className="fixed z-50 w-56 rounded-2xl border border-white/10 bg-ink-950 p-2 text-sm shadow-2xl"
          style={{ left: contextPos.x, top: contextPos.y }}
          onMouseLeave={() => setContextFolder(null)}
        >
          <button className="w-full rounded-xl px-3 py-2 text-left hover:bg-white/10" onClick={() => { setEditingFolderId(contextFolder.id); setEditingFolderName(contextFolder.name); setContextFolder(null); }}>Rename folder</button>
          <button className="w-full rounded-xl px-3 py-2 text-left hover:bg-white/10" onClick={() => { moveFolder?.(contextFolder.id, null); setContextFolder(null); }}>Move to root</button>
          <button className="w-full rounded-xl px-3 py-2 text-left text-red-300 hover:bg-red-500/10" onClick={() => { deleteFolder?.(contextFolder.id); setContextFolder(null); }}>Delete empty folder</button>
        </div>

      )}

      <div className="mb-3 rounded-xl border border-white/10 bg-white/5 p-3">

        <button
            className="mb-3 w-full rounded-lg border border-white/10 px-3 py-2 hover:bg-white/10"
            onClick={()=>setShowStats(v=>!v)}
        >
            {showStats ? "▼ Στατιστικά" : "▶ Στατιστικά"}
        </button>

        {showStats && (

        <div className="space-y-2 text-sm">

            <div className="flex justify-between">
                <span>Έγγραφα</span>
                <strong>{documents.length}</strong>
            </div>

            <div className="flex justify-between">
                <span>Φάκελοι</span>
                <strong>{folders.length}</strong>
            </div>

            <div className="flex justify-between">
                <span>Κατηγορίες</span>
                <strong>{categories.length}</strong>
            </div>

        </div>

        )}

      </div>

      <div className="space-y-3 pr-1">

        {loading && (
          <SidebarEmptyState
            title="Φόρτωση βιβλιοθήκης"
            text="Ανάκτηση εγγράφων, φακέλων και προτύπων."
          />
        )}

        {!loading && documents.length === 0 && (
          <SidebarEmptyState
            title="Δεν υπάρχουν ακόμη έγγραφα"
            text="Δημιουργήστε ή εισαγάγετε ένα εταιρικό έγγραφο."
          />
        )}

        {documents.map((document) => {
          const stats = documentStats(document);
          const isSelected =
            selectedDocument?.id === document.id;

          return (
            <button
              key={document.id}
              type="button"
              onClick={() => onSelectDocument(document)}
              className={`w-full rounded-2xl border p-4 text-left transition focus:outline-none focus:ring-2 focus:ring-gold/50 ${
                isSelected
                  ? "border-gold bg-gold/10"
                  : "border-white/10 bg-white/[0.04] hover:bg-white/[0.07]"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-2">
                  <input type="checkbox" checked={selectedIds.includes(document.id)} onChange={(event) => { event.stopPropagation(); onToggleSelected?.(document.id); }} onClick={(event) => event.stopPropagation()} />
                  <div className="font-medium">
                    {document.title}
                  </div>
                </div>

                <FileText className="h-4 w-4 shrink-0 text-gold" />
              </div>

              <p className="mt-2 line-clamp-3 text-xs text-white/50">
                {summarizeDocument(document)}
              </p>

              <div className="mt-3 flex flex-wrap gap-2 text-[10px] uppercase tracking-wider text-white/45">
                <span>{document.category || "General"}</span>
                <span>v{stats.versions}</span>
                <span>{stats.words} λέξεις</span>

                {document.country && (
                  <span>{document.country}</span>
                )}

                {document.language && (
                  <span>{document.language}</span>
                )}
              </div>

              {(document.tags || []).length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1">
                  {document.tags.slice(0, 5).map((tag) => (
                    <span
                      key={tag}
                      className="rounded-full border border-gold/20 bg-gold/10 px-2 py-1 text-[9px] text-gold"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </button>
          );
        })}
      </div>
    </aside>

    )}

    </>
  );
}

function SidebarEmptyState({ title, text }) {
  return (
    <div className="rounded-2xl border border-dashed border-white/10 bg-black/20 p-4 text-center">
      <div className="text-sm text-white/70">
        {title}
      </div>

      <div className="mt-1 text-xs text-white/40">
        {text}
      </div>
    </div>
  );
}
