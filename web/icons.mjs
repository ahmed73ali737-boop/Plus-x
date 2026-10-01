const paths={
 spark:['m12 3 2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6Z'],
 arrow:['M19 12H5','m11 6-6 6 6 6'],
 layers:['m12 3 9 5-9 5-9-5 9-5Z','m3 12 9 5 9-5','m3 16 9 5 9-5'],
 building:['M4 21V6h10v15','M14 11h6v10','M2 21h20','M8 10h2','M8 14h2','M8 18h2','M17 15h1'],
 chart:['M4 3v18h17','M8 16v-4','M13 16V8','M18 16V5'],
 message:['M21 11a8 8 0 0 1-8 8H6l-4 3V11a9 9 0 0 1 19 0Z','M7 9h9','M7 13h6'],
 star:['m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9Z'],
 gift:['M3 8h18v4H3Z','M5 12v9h14v-9','M12 8v13','M12 8H8a3 3 0 1 1 3-3Zm0 0h4a3 3 0 1 0-3-3Z'],
 play:['m9 5 11 7-11 7V5Z'],
 calendar:['M4 5h16v16H4Z','M8 3v4','M16 3v4','M4 10h16','M8 14h2','M14 14h2'],
 check:['m5 12 4 4L19 6'],
 shield:['m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z','m8 12 3 3 5-6'],
 menu:['M4 6h16','M4 12h16','M4 18h16'],
 plus:['M12 4v16','M4 12h16'],
 close:['m6 6 12 12','M6 18 18 6'],
};
export function icon(name,size=24){const ns='http://www.w3.org/2000/svg';const s=document.createElementNS(ns,'svg');for(const[k,v]of Object.entries({viewBox:'0 0 24 24',width:size,height:size,fill:'none',stroke:'currentColor','stroke-width':'1.65','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false'}))s.setAttribute(k,v);for(const d of paths[name]||paths.spark){const p=document.createElementNS(ns,'path');p.setAttribute('d',d);s.append(p);}return s;}
