
export const translations={

el:{

search:"Αναζήτηση",
category:"Κατηγορία",
folder:"Φάκελος",
country:"Χώρα",
language:"Γλώσσα",
tags:"Tags",
documents:"Έγγραφα",
preview:"Προεπισκόπηση",
download:"Λήψη",
rename:"Μετονομασία",
delete:"Διαγραφή",
duplicate:"Αντίγραφο",
move:"Μετακίνηση",
empty:"Δεν βρέθηκαν έγγραφα",
clearFilters:"Καθαρισμός φίλτρων"

},

en:{

search:"Search",
category:"Category",
folder:"Folder",
country:"Country",
language:"Language",
tags:"Tags",
documents:"Documents",
preview:"Preview",
download:"Download",
rename:"Rename",
delete:"Delete",
duplicate:"Duplicate",
move:"Move",
empty:"No documents found",
clearFilters:"Clear filters"

}

};

export function t(lang,key){

return(
translations[lang]?.[key] ??
translations.el[key] ??
key
);

}
