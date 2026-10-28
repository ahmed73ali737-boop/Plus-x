import {h,button,field,selectField,api,newRequestKey} from './ui.mjs';
import {A,message,upload,preview} from './self-certificate-client.mjs';
const clone=value=>structuredClone(value),equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
export async function openSelfCertificateEditor(model,onSaved){
 let draft=model?{name:model.name,background_asset_id:model.revision.background_asset_id,stamp_asset_id:model.revision.stamp_asset_id,config:clone(model.revision.config)}:{name:'',background_asset_id:null,stamp_asset_id:null,config:null};
 let saved=clone(draft),history=[clone(draft)],at=0,meta=null,sampleEnglish=false,previewURL=null,sequence=0,timer,closed=false,previewReady=false,saving=false,previewController=null,pendingCreate=null,uploading=false;
 const invoker=document.activeElement;let fieldSignature=null,bindings=[];
 const dialog=h('dialog',{class:'selfcert-editor',dir:'rtl','aria-labelledby':'selfcert-editor-title'}),status=h('p',{class:'selfcert-editor-status',role:'status'});
 const props=h('aside',{class:'selfcert-properties'}),stage=h('div',{class:'selfcert-stage',dir:'ltr'});
 const background=h('img',{class:'selfcert-background',alt:'خلفية الشهادة',draggable:false});
 const rendered=h('img',{class:'selfcert-background',alt:'بروفة من محرك الصورة النهائية',hidden:true,draggable:false});
 const fallback=h('div',{class:'selfcert-card',dir:'ltr'},h('span',{},'Powered by'),h('img',{src:A+'/branding/rts.png',alt:'RTS',draggable:false}));
 const nameBox=h('div',{class:'selfcert-name-box',tabindex:0,'aria-label':'تحريك مستطيل الاسم'},h('span',{class:'selfcert-handle','data-resize':'1',tabindex:0,role:'button','aria-label':'تحجيم مساحة الاسم بالأسهم'}));
 const stampBox=h('div',{class:'selfcert-stamp-box',tabindex:0,'aria-label':'تحريك مستطيل الختم'},h('span',{class:'selfcert-handle','data-resize':'1',tabindex:0,role:'button','aria-label':'تحجيم مساحة الختم بالأسهم'}));
 stage.append(background,rendered,fallback,nameBox,stampBox);
 const emptyWorkspace=h('div',{class:'selfcert-editor-empty'},h('strong',{},'ابدأ بخلفية شهادتك'),h('p',{},'ارفع صورة أو PDF من لوحة الخصائص، ثم حرّك مساحة الاسم والختم داخل المعاينة.'));
 const viewport=h('div',{class:'selfcert-viewport'},stage,emptyWorkspace);
 const zoom=selectField('تكبير المعاينة',[['width','ملاءمة العرض'],['fit','عرض الصفحة كاملة'],['0.5','50%'],['0.75','75%'],['1','100%']], 'width');
 const undo=button('تراجع عن تعديل',()=>step(-1),'btn secondary'),redo=button('إعادة تعديل',()=>step(1),'btn secondary');
 const sample=button('عينة إنجليزية',()=>{sampleEnglish=!sampleEnglish;sample.textContent=sampleEnglish?'عينة عربية':'عينة إنجليزية';schedule();},'btn secondary');
 const name=field('اسم النموذج','text',draft.name,{maxLength:160});
 const header=h('header',{},h('h2',{id:'selfcert-editor-title'},model?'تعديل نموذج الشهادة':'إضافة نموذج شهادة'),button('إغلاق',()=>closePrompt(),'icon-btn'));
 const saveButton=h('button',{type:'button',class:'btn',onclick:()=>save()},'حفظ النموذج');saveButton.disabled=true;
 const footer=h('footer',{class:'selfcert-editor-footer'},status,
  button('تجاهل وإغلاق',()=>closePrompt(),'btn secondary'),
  saveButton);
 dialog.append(header,h('div',{class:'selfcert-editor-body'},h('section',{class:'selfcert-workspace'},
  h('div',{class:'selfcert-toolbar'},undo,redo,sample,button('تحديث البروفة',refreshPreview,'btn secondary'),zoom.node),viewport,
  h('p',{class:'notice small'},'بطاقة RTS ثابتة أسفل اليسار. قد تغطي كتابة مطبوعة في الخلفية؛ راجع البروفة. لا تُكتشف الكتابة آليًا.')),
  props),footer);
 const conflict=h('section',{class:'selfcert-conflict',hidden:true,role:'alert'},
  h('p',{},'حفظت جلسة أخرى نسخة أحدث. تعديلك في هذه النافذة ما زال محفوظًا هنا.'),
  button('مراجعة النسخة المحفوظة',async()=>{
   if(!confirm('تحميل النسخة المحفوظة يستبدل تعديل هذه النافذة. هل تتابع؟'))return;
   try{model=await api(A+'/models/'+model.id);draft={name:model.name,background_asset_id:model.revision.background_asset_id,stamp_asset_id:model.revision.stamp_asset_id,config:clone(model.revision.config)};
    saved=clone(draft);history=[clone(draft)];at=0;await loadMeta();conflict.hidden=true;sync();schedule();}
   catch(e){status.textContent=message(e);}
  },'btn secondary'),
  button('حفظ تعديلي كنموذج جديد',()=>save(true),'btn secondary'));
 footer.append(conflict);
 function dirty(){return !equal(saved,draft)||name.input.value!==saved.name;}
 function valid(config,candidate=draft){
  if(!meta||!config)return false;
  const r=meta.branding_manifest.card_rect,gap=meta.branding_manifest.clearance;
  for(const rect of [config.name_rect,...(candidate.stamp_asset_id?[config.stamp_rect]:[])]){
   if(!rect||rect.width<=0||rect.height<=0||rect.x<0||rect.y<0||rect.x+rect.width>meta.width||rect.y+rect.height>meta.height)return false;
   if(rect.x+rect.width>=r.x-gap&&rect.x<=r.x+r.width+gap&&rect.y+rect.height>=r.y-gap&&rect.y<=r.y+r.height+gap)return false;
  }
  return true;
 }
 function commit(next,allowInvalid=false){
  if(closed||saving)return false;
  if(next.config&&!allowInvalid&&!valid(next.config,next)){configFields();draw();status.textContent='الموضع خارج الخلفية أو داخل مساحة RTS المحجوزة.';return false;}
  if(equal(next,draft))return true;
  const designChanged=!equal([draft.background_asset_id,draft.stamp_asset_id,draft.config],[next.background_asset_id,next.stamp_asset_id,next.config]);
  draft=clone(next);history=history.slice(0,at+1);history.push(clone(draft));if(history.length>100)history.shift();at=history.length-1;
  sync(designChanged);if(designChanged)schedule();return true;
 }
 async function step(delta){if(saving||uploading)return;if(at+delta<0||at+delta>=history.length)return;at+=delta;draft=clone(history[at]);await loadMeta();sync();schedule();}
 async function loadMeta(){
  if(!draft.background_asset_id){meta=null;return;}
  meta=await api(A+'/design-options?background_id='+encodeURIComponent(draft.background_asset_id)+'&has_stamp='+Boolean(draft.stamp_asset_id));
 }
 function place(node,rect){
  if(!meta||!rect){node.hidden=true;return;}node.hidden=false;
  Object.assign(node.style,{left:rect.x/meta.width*100+'%',top:rect.y/meta.height*100+'%',width:rect.width/meta.width*100+'%',height:rect.height/meta.height*100+'%'});
 }
 function draw(){
  emptyWorkspace.hidden=Boolean(meta);
  if(!meta){stage.hidden=true;return;}
  stage.hidden=false;stage.style.aspectRatio=meta.width+'/'+meta.height;
  const style=getComputedStyle(viewport),space=(...keys)=>keys.reduce((sum,key)=>sum+(parseFloat(style[key])||0),0);
  const width=Math.max(1,viewport.clientWidth-space('paddingLeft','paddingRight'));
  const height=Math.max(1,viewport.clientHeight-space('paddingTop','paddingBottom'));
  const ratio=meta.width/meta.height,mode=zoom.input.value;
  // Display scale only: neither native pixels nor saved geometry are changed.
  const displayWidth=mode==='width'?width:mode==='fit'?Math.min(width,height*ratio):meta.width*Number(mode);
  stage.style.width=Math.max(1,displayWidth)+'px';
  stage.style.height=Math.max(1,displayWidth/ratio)+'px';
  background.src=meta.background_url;
  place(fallback,meta.branding_manifest.card_rect);fallback.hidden=!rendered.hidden;
  place(nameBox,draft.config?.name_rect);place(stampBox,draft.stamp_asset_id?draft.config?.stamp_rect:null);
  undo.disabled=at===0;redo.disabled=at===history.length-1;
 }
 function updateConfig(key,value){const next=clone(draft);next.config[key]=value;commit(next);}
 function configFields(){
  const signature=JSON.stringify([Boolean(meta&&draft.config),Boolean(draft.stamp_asset_id),meta?.fonts?.map(f=>f.id)]);
  if(signature===fieldSignature){for(const update of bindings)update();return;}
  fieldSignature=signature;bindings=[];
  props.replaceChildren(name.node);
  const bg=field('خلفية PNG أو JPEG أو PDF','file','',{accept:'.png,.jpg,.jpeg,.pdf'});
  const stamp=field('ختم PNG اختياري','file','',{accept:'.png'});stamp.input.disabled=!meta;
  bg.input.addEventListener('change',()=>{const file=bg.input.files[0];bg.input.value='';uploadFile(file,'background');});
  stamp.input.addEventListener('change',()=>{const file=stamp.input.files[0];stamp.input.value='';uploadFile(file,'stamp');});
  props.append(h('h3',{},'الخلفية والختم'),bg.node,h('p',{class:'selfcert-property-help'},'PNG أو JPEG أو PDF من صفحة واحدة · حتى 3 ميغابايت.'),stamp.node,h('p',{class:'selfcert-property-help'},'ختم PNG اختياري · أقل من 1 ميغابايت.'));
  if(!draft.config||!meta)return;
  props.append(h('h3',{},'تنسيق اسم المشارك'));
  const selections=[
   ['الخط','font_id',meta.fonts.map(x=>[x.id,x.family+' · '+(x.weight==='Bold'?'عريض':'عادي')])],
   ['اتجاه الاسم','direction',[['rtl','من اليمين'],['ltr','من اليسار']]],
   ['المحاذاة الأفقية','align',[['left','يسار'],['center','وسط'],['right','يمين']]],
   ['المحاذاة الرأسية','vertical_align',[['top','أعلى'],['middle','وسط'],['bottom','أسفل']]]];
  for(const[label,key,values]of selections){const f=selectField(label,values,draft.config[key]);f.input.addEventListener('change',()=>updateConfig(key,f.input.value));bindings.push(()=>{if(f.input.value!==String(draft.config[key]))f.input.value=draft.config[key];});props.append(f.node);}
  for(const[label,key,type]of[['الحجم المفضل','preferred_size','number'],['أصغر حجم','minimum_size','number'],['لون الاسم','color','color']]){
   const f=field(label,type,draft.config[key],type==='number'?{min:1,max:1024}:{});
   f.input.addEventListener('change',()=>updateConfig(key,type==='number'?Number(f.input.value):f.input.value));bindings.push(()=>{if(f.input.value!==String(draft.config[key]))f.input.value=draft.config[key];});props.append(f.node);
  }
  const advanced=h('details',{class:'selfcert-advanced',open:true},h('summary',{},'المواضع المتقدمة · بكسلات الصورة الأصلية'));props.append(advanced);
  for(const[label,key]of[['الاسم','name_rect'],...(draft.stamp_asset_id?[['الختم','stamp_rect']]:[])]){
   advanced.append(h('h3',{},'مساحة '+label+' · بكسل أصلي'));
   for(const [title,coordinate]of[['الموضع الأفقي','x'],['الموضع الرأسي','y'],['العرض','width'],['الارتفاع','height']]){
    const f=field(label+' · '+title,'number',draft.config[key][coordinate],{step:1});
    f.input.addEventListener('change',()=>{const next=clone(draft);next.config[key][coordinate]=Number(f.input.value);commit(next);});bindings.push(()=>{if(f.input.value!==String(draft.config[key][coordinate]))f.input.value=draft.config[key][coordinate];});advanced.append(f.node);
   }
  }
  if(draft.stamp_asset_id)props.append(button('إزالة الختم',()=>{const next=clone(draft);next.stamp_asset_id=null;next.config.stamp_rect=null;commit(next);},'btn secondary'));
  props.append(button('إعادة ضبط التخطيط',()=>{if(confirm('إعادة مواضع الاسم والختم وتنسيق الاسم إلى التخطيط الافتراضي؟'))commit({...draft,config:clone(meta.default_config)});},'btn secondary'));
 }
 function sync(invalidate=true){if(name.input.value!==draft.name)name.input.value=draft.name;if(invalidate)rendered.hidden=true;configFields();draw();status.textContent=dirty()?'تغييرات غير محفوظة':'النسخة المحفوظة';}
 name.input.addEventListener('change',()=>commit({...draft,name:name.input.value}));
 async function uploadFile(file,kind){
  if(!file||saving||uploading)return;uploading=true;previewReady=false;saveButton.disabled=true;props.inert=true;dialog.querySelector('.selfcert-workspace').inert=true;status.textContent='جارٍ فحص الملف…';
  try{
   const asset=await upload(file,kind);if(closed)return;const next=clone(draft);
   if(kind==='background'){
    next.background_asset_id=asset.id;
    const options=await api(A+'/design-options?background_id='+asset.id+'&has_stamp='+Boolean(next.stamp_asset_id));
    meta=options;if(!next.config)next.config=clone(options.default_config);
   }else{
    if(!meta)throw new Error('BACKGROUND_REQUIRED');
    next.stamp_asset_id=asset.id;
    let w=Math.min(meta.width*.18,asset.width),hh=w*asset.height/asset.width;
    if(hh>meta.height*.25){hh=meta.height*.25;w=hh*asset.width/asset.height;}
    next.config.stamp_rect={x:Math.round(meta.width-w-meta.width*.04),y:Math.round(meta.height-hh-meta.height*.04),width:Math.round(w),height:Math.round(hh)};
   }
   commit(next,true);
   if(!valid(next.config))status.textContent='الخلفية الجديدة تحتاج تصحيح المواضع. استخدم إعادة ضبط التخطيط أو عدّل المساحات قبل الحفظ.';
  }catch(e){status.textContent=message(e);}
  finally{uploading=false;props.inert=false;dialog.querySelector('.selfcert-workspace').inert=false;if(!closed&&draft.config)schedule();}
 }
 function schedule(){sequence++;previewReady=false;previewController?.abort();saveButton.disabled=true;status.textContent="جارٍ تجهيز البروفة الحديثة…";clearTimeout(timer);rendered.hidden=true;fallback.hidden=false;timer=setTimeout(refreshPreview,350);}
 async function refreshPreview(){
  if(closed||!meta||!draft.config)return;
  const current=++sequence;previewController?.abort();previewController=new AbortController();
  try{
   const blob=await preview({background_asset_id:draft.background_asset_id,stamp_asset_id:draft.stamp_asset_id,config:draft.config,
    sample_name:sampleEnglish?'John Michael David Robert Smith':'محمد أحمد علي حسن العمري'},previewController.signal);
   if(closed||current!==sequence)return;
   if(previewURL)URL.revokeObjectURL(previewURL);previewURL=URL.createObjectURL(blob);rendered.src=previewURL;rendered.hidden=false;fallback.hidden=true;previewReady=true;saveButton.disabled=saving;
   status.textContent=dirty()?'البروفة محدثة · تغييرات غير محفوظة':'البروفة مطابقة لمحرك الإخراج';
  }catch(e){if(current===sequence&&e.name!=='AbortError')status.textContent=message(e);}
 }
 function drag(node,key){
  node.addEventListener('pointerdown',event=>{
   if(!draft.config||event.button!==0)return;
   event.preventDefault();node.setPointerCapture(event.pointerId);
   const before=clone(draft),rect=clone(draft.config[key]),bounds=stage.getBoundingClientRect(),startX=event.clientX,startY=event.clientY;
   const resize=!!event.target.dataset.resize,ratio=rect.width/rect.height;
   let latest=rect;
   const move=e=>{
    const dx=(e.clientX-startX)*meta.width/bounds.width,dy=(e.clientY-startY)*meta.height/bounds.height;
    const next=clone(rect);
    if(resize){next.width=Math.max(8,Math.round(rect.width+dx));next.height=key==='stamp_rect'?Math.max(8,Math.round(next.width/ratio)):Math.max(8,Math.round(rect.height+dy));}
    else{next.x=Math.round(rect.x+dx);next.y=Math.round(rect.y+dy);}
    const candidate=clone(before.config);candidate[key]=next;
    if(valid(candidate)){latest=next;place(node,next);}else status.textContent='هذه المساحة خارج الخلفية أو محجوزة لـRTS.';
   };
   const finish=()=>{node.removeEventListener('pointermove',move);node.removeEventListener('pointerup',finish);node.removeEventListener('pointercancel',finish);const next=clone(before);next.config[key]=latest;commit(next);};
   node.addEventListener('pointermove',move);node.addEventListener('pointerup',finish);node.addEventListener('pointercancel',finish);
  });
  node.addEventListener('keydown',event=>{
   const delta={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[event.key];if(!delta)return;
   event.preventDefault();const next=clone(draft),step=event.shiftKey?10:1,rect=next.config[key];
   if(event.target.dataset.resize){
    if(key==='stamp_rect'){const ratio=rect.width/rect.height;rect.width=Math.max(8,rect.width+(delta[0]||delta[1])*step);rect.height=Math.max(8,Math.round(rect.width/ratio));}
    else{rect.width=Math.max(8,rect.width+delta[0]*step);rect.height=Math.max(8,rect.height+delta[1]*step);}
   }else{rect.x+=delta[0]*step;rect.y+=delta[1]*step;}
   commit(next);
  });
 }
 drag(nameBox,'name_rect');drag(stampBox,'stamp_rect');
 async function save(asCopy=false){
  if(saving||uploading)return;
  try{
   if(!previewReady){status.textContent='انتظر اكتمال البروفة الحديثة قبل الحفظ.';return;}
   if(!draft.background_asset_id||!draft.config||!name.input.value.trim())throw new Error('MODEL_INPUT_INVALID');
   saving=true;saveButton.disabled=true;props.inert=true;stage.inert=true;dialog.querySelector('.selfcert-workspace').inert=true;status.textContent='جارٍ حفظ النموذج…';
   draft.name=name.input.value.trim();
   if(asCopy){model=null;pendingCreate=null;conflict.hidden=true;}
   const current=clone(draft);
   if(!model){
    if(!pendingCreate)pendingCreate={key:newRequestKey(),body:clone(current)};
    // Recover an earlier accepted create before saving edits made after its
    // lost acknowledgement; never silently create a second model.
    const created=await api(A+'/models',{...pendingCreate.body,idempotency_key:pendingCreate.key});
    model=created;
    const recovered=clone(pendingCreate.body);pendingCreate=null;
    if(!equal(current,recovered)){
     model=await api(A+'/models/'+model.id,{...current,row_version:model.row_version},'PUT');
    }
   }else{
    model=await api(A+'/models/'+model.id,{...current,row_version:model.row_version},'PUT');
   }
   saved=clone(current);conflict.hidden=true;await onSaved(model);dialog.close();
  }catch(e){
   status.textContent=message(e);
   if(e.status===409&&e.message==='VERSION_CONFLICT')conflict.hidden=false;
   else if(pendingCreate)status.textContent+=' قد يكون الحفظ اكتمل؛ أعد الحفظ من هذه النافذة لاستعادة العملية نفسها.';
  }finally{saving=false;props.inert=false;stage.inert=false;dialog.querySelector('.selfcert-workspace').inert=false;saveButton.disabled=!previewReady;}
 }

 function closePrompt(){if(saving){status.textContent='انتظر تأكيد الحفظ قبل الإغلاق.';return;}if(!dirty()||confirm('لديك تعديلات غير محفوظة. تجاهلها وإغلاق المحرر؟'))dialog.close();}
 const unload=e=>{if(dirty()){e.preventDefault();e.returnValue='';}};
 dialog.addEventListener('cancel',e=>{e.preventDefault();closePrompt();});
 dialog.addEventListener('close',()=>{closed=true;sequence++;previewController?.abort();clearTimeout(timer);if(previewURL)URL.revokeObjectURL(previewURL);observer.disconnect();window.removeEventListener('beforeunload',unload);dialog.remove();if(invoker?.isConnected)invoker.focus({preventScroll:true});});
 window.addEventListener('beforeunload',unload);
 document.body.append(dialog);dialog.showModal();name.input.focus({preventScroll:true});
 const observer=new ResizeObserver(draw);observer.observe(viewport);zoom.input.addEventListener('change',draw);
 await loadMeta();
 if(model?.revision.schema_version<2&&meta){status.textContent='هذه نسخة قديمة. راجع التخطيط قبل حفظ نسخة جديدة؛ لا تتغير الروابط السابقة.';}
 sync();schedule();
}
