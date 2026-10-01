/** Presentation catalogue. Navigation changes the view, never the submitted data. */
export const sectionsMeta = {
  event: {icon:'building', eyebrow:'MEET & CONNECT', description:'تعرّف على الفعالية والجهات المشاركة والرعاة، واستكشف البرنامج والأماكن.'},
  facts: {icon:'chart', eyebrow:'FACTS & INSIGHTS', description:'أرقام وحقائق تنشرها الجهة، مع مصدر كل معلومة وطريقة عرضها.'},
  about: {icon:'spark', eyebrow:'OUR STORY', description:'عن الجهة، رؤيتها، وما تقدمه لجمهورها وشركائها.'},
  services: {icon:'layers', eyebrow:'WHAT WE OFFER', description:'اكتشف الخدمات والحلول، وافتح كل خدمة لمعرفة تفاصيلها والتواصل بشأنها.'},
  questions: {icon:'message', eyebrow:'YOUR VOICE MATTERS', description:'استبيانات متنوعة ومساحة لرأيك. المشاركة متاحة دون تسجيل أو بيانات شخصية.'},
  polls: {icon:'chart', eyebrow:'VOTE & DISCOVER', description:'شارك باختيارك، وتابع النتائج المستلمة عندما تسمح الجهة بعرضها.'},
  ratings: {icon:'star', eyebrow:'SHARE YOUR EXPERIENCE', description:'تقييم مستقل وملاحظات خاصة تساعد الجهة والمنظّم على التحسين.'},
  contact: {icon:'message', eyebrow:'LET’S CONNECT', description:'طرق التواصل الرسمية، وطلب متابعة اختياري بموافقة منفصلة.'},
  offers: {icon:'gift', eyebrow:'OFFERS & OPPORTUNITIES', description:'العروض والمحتوى الترويجي المنشور، دون خلطه بنتائج الجمهور.'},
  media: {icon:'play', eyebrow:'IN THE SPOTLIGHT', description:'صور وفيديوهات تعرّفك بالجهة والفعالية والأماكن والخدمات.'},
  events: {icon:'calendar', eyebrow:'EXPLORE EXPERIENCES', description:'تصفّح الفعاليات الحالية والقادمة، وافتح الموقع المستقل لكل فعالية.'},
  news: {icon:'message', eyebrow:'LATEST STORIES', description:'أخبار ومستجدات ونتائج تنشرها إدارة المنصة.'}
};
export function snippet(value,limit=145){const s=String(value||'').trim();return s.length>limit?s.slice(0,limit).trimEnd()+'…':s;}
export function route(hash){
  const raw=String(hash||'').replace(/^#/,'');
  const parts=raw.split('/').map(v=>{try{return decodeURIComponent(v);}catch{return '';}});
  if(parts[0]==='section'&&parts[1])return {type:'section',key:parts[1]};
  if(parts[0]==='item'&&parts[1]&&parts[2])return {type:'item',scope:parts[1],code:parts[2]};
  return {type:'home',anchor:parts[0]||''};
}
export function itemLink(scope,code){return '#item/'+encodeURIComponent(scope)+'/'+encodeURIComponent(code);}
export function sectionLink(key){return '#section/'+encodeURIComponent(key);}
