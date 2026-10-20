import {h,api,field,selectField,button,modal,toast} from './ui.mjs';
async function readImage(file){if(!file||file.size>1000000)throw new Error('اختر صورة PNG أو JPEG أصغر من 1 ميجابايت.');return await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(file);});}
export function certificateEditor({base,templates,onSave}){
 let design=structuredClone(templates.default_design);
 const card=h('section',{class:'card'}),name=field('اسم نسخة القالب','text','شهادة مشاركة',{maxlength:160,required:true});
 const source=selectField('ابدأ من قالب',[['','قالب جديد'],...templates.items.map(t=>[t.id,t.name])],'');
 const stage=h('div',{class:'certificate-stage','aria-label':'معاينة طبقات الشهادة'}),controls=h('div');
 const bg=field('خلفية الشهادة PNG أو JPEG','file','',{accept:'image/png,image/jpeg'});
 const imageFile=field('إضافة توقيع أو ختم PNG شفاف','file','',{accept:'image/png,image/jpeg'});
 const color=field('لون الخلفية','color',design.background);
 const qrX=field('QR: الموضع الأفقي','number',design.qr.x,{min:0}),qrY=field('QR: الموضع الرأسي','number',design.qr.y,{min:0});
 const qrSize=field('حجم QR','number',design.qr.size,{min:100,max:396});
 let revision=0;
 async function preview(){const rev=++revision;Object.assign(design,{background:color.input.value,qr:{x:Number(qrX.input.value),y:Number(qrY.input.value),size:Number(qrSize.input.value)}});const response=await api(base+'/certificates/preview',{design});if(rev!==revision)return;const url=URL.createObjectURL(new Blob([response.svg],{type:'image/svg+xml'}));const img=h('img',{src:url,alt:'معاينة القالب غير الصادر'});img.onload=()=>URL.revokeObjectURL(url);stage.replaceChildren(img);
  design.layers.forEach((layer,index)=>{const hit=h('button',{type:'button',class:'certificate-handle','aria-label':'تحريك الطبقة '+(index+1),style:`left:${100*layer.x/design.width}%;top:${100*layer.y/design.height}%;`},'↔');
   const move=(x,y)=>{const w=layer.kind==='image'?layer.width:0,h=layer.kind==='image'?layer.height:0;layer.x=Math.max(0,Math.min(design.width-w,x));layer.y=Math.max(0,Math.min(design.height-h,y));hit.style.left=100*layer.x/design.width+'%';hit.style.top=100*layer.y/design.height+'%';};
   let dragging=false,offsetX=0,offsetY=0;
   hit.addEventListener('pointerdown',e=>{const rect=stage.getBoundingClientRect();offsetX=(e.clientX-rect.left)*design.width/rect.width-layer.x;offsetY=(e.clientY-rect.top)*design.height/rect.height-layer.y;dragging=true;hit.setPointerCapture(e.pointerId);e.preventDefault();});
   hit.addEventListener('pointermove',e=>{if(!dragging)return;const r=stage.getBoundingClientRect();move((e.clientX-r.left)*design.width/r.width-offsetX,(e.clientY-r.top)*design.height/r.height-offsetY);});
   hit.addEventListener('pointerup',async()=>{if(!dragging)return;dragging=false;drawControls();try{await preview();}catch(e){toast(e.message,true);}});
   hit.addEventListener('keydown',async e=>{const delta={ArrowLeft:[-5,0],ArrowRight:[5,0],ArrowUp:[0,-5],ArrowDown:[0,5]}[e.key];if(!delta)return;e.preventDefault();move(layer.x+delta[0],layer.y+delta[1]);drawControls();try{await preview();}catch(error){toast(error.message,true);}});stage.append(hit);
  });
 }
 function drawControls(){controls.replaceChildren();design.layers.forEach((layer,index)=>{const row=h('fieldset',{class:'card mini'},h('legend',{},layer.kind==='image'?'صورة / توقيع':'طبقة نص '+(index+1)));
  for(const [key,label,type]of (layer.kind==='image'?[['x','X','number'],['y','Y','number'],['width','العرض','number'],['height','الارتفاع','number']]:[['text','النص أو المتغير','text'],['x','X','number'],['y','Y','number'],['size','حجم الخط','number'],['color','لون النص','color']])){const f=field(label,type,layer[key]??(key==='color'?'#17313b':''));f.input.addEventListener('input',()=>{layer[key]=type==='number'?Number(f.input.value):f.input.value;});row.append(f.node);}
  if(layer.kind!=='image'){for(const [key,label,choices]of [['direction','اتجاه النص',[['rtl','عربي RTL'],['ltr','إنجليزي LTR']]],['align','محاذاة النص',[['middle','وسط'],['start','بداية'],['end','نهاية']]]]){const f=selectField(label,choices,layer[key]||(key==='align'?'middle':'rtl'));f.input.onchange=()=>layer[key]=f.input.value;row.append(f.node);}}
  row.append(button('حذف الطبقة',()=>{if(design.layers.length===1)return;design.layers.splice(index,1);drawControls();}));controls.append(row);
 });}
 source.input.onchange=()=>{design=structuredClone(templates.items.find(t=>t.id===source.input.value)?.design||templates.default_design);color.input.value=design.background;qrX.input.value=design.qr.x;qrY.input.value=design.qr.y;qrSize.input.value=design.qr.size;drawControls();};
 bg.input.onchange=async()=>{try{design.background_image=await readImage(bg.input.files[0]);await preview();}catch(e){toast(e.message,true);}};
 imageFile.input.onchange=async()=>{try{if(design.layers.length>=40)throw new Error('الحد الأقصى 40 طبقة.');design.layers.push({kind:'image',image_data:await readImage(imageFile.input.files[0]),x:780,y:580,width:180,height:90});drawControls();await preview();}catch(e){toast(e.message,true);}};
 card.append(h('h3',{},'مصمم الشهادات'),source.node,name.node,h('p',{class:'muted'},'استخدم المتغيرات {{participant_name}} و{{course_title}} و{{issuer_name}} و{{issue_date}} و{{serial}}. حرّك الطبقات بالسحب أو الأسهم بعد المعاينة، أو أدخل المواضع رقميًا. الخط العربي المرفق ثابت في التصدير.'),stage,bg.node,button('إزالة الخلفية',()=>{delete design.background_image;}),imageFile.node,color.node,h('div',{class:'grid'},qrX.node,qrY.node,qrSize.node),controls,
 button('إضافة نص',()=>{if(design.layers.length>=40)return;design.layers.push({text:'نص جديد',x:560,y:200,size:28});drawControls();}),button('تحديث المعاينة',preview),button('حفظ نسخة القالب',async()=>{if(!name.input.reportValidity())return;await preview();await api(base+'/certificate-templates',{name:name.input.value,design});await onSave();}));
 drawControls();return card;
}
