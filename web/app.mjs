import {root,h,msg,button} from './ui.mjs';
import {publicPage} from './public.mjs';
import {adminPage} from './admin.mjs';
try{if(location.pathname==='/admin'||location.pathname.startsWith('/admin/'))await adminPage();else{const parts=location.pathname.split('/').filter(Boolean);const slug=parts.includes('p')?parts[parts.indexOf('p')+1]:parts[0]==='e'?parts[1]:'platform';await publicPage(slug);}}catch(e){root.replaceChildren(h('main',{class:'error-page'},h('h1',{},'تعذر فتح هذه الصفحة'),h('p',{},msg(e)),h('p',{class:'muted'},'أول فتح وتحميل المحتوى يحتاجان اتصالًا. لا تصبح صفحة جديدة متاحة بلا إنترنت قبل تجهيزها.'),button('إعادة المحاولة',()=>location.reload()),h('a',{href:'/',class:'text-btn'},'الرئيسية')));console.error(e);}
