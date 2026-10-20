package com.pulsex.app;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.util.Base64;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.*;
import android.widget.*;
import org.json.JSONObject;
import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Android host for the canonical Eventna إيفنتنا application. No copied backend or identity store. */
public final class MainActivity extends Activity {
    private static final int INK=0xff102c34, TEAL=0xff11796f, MUTED=0xff5a7178, BG=0xfff4f8f7;
    private static final int FILE_PICK=40, FILE_SAVE=41, CAMERA=42, QR_SCAN=43, MAX_EXPORT=8*1024*1024;
    private final ExecutorService io=Executors.newSingleThreadExecutor();
    private LinearLayout root, content, webHolder;
    private WebView web;
    private ProgressBar progress;
    private TextView webTitle;
    private SharedPreferences prefs;
    private String server="", slug="demo", currentPath="/";
    private PermissionRequest cameraRequest;
    private ValueCallback<Uri[]> fileCallback;
    private byte[] pendingExport;
    private boolean home=true, checking=false;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        prefs=getSharedPreferences("pulsex",MODE_PRIVATE);
        try { server=ServerPolicy.normalize(prefs.getString("server",ServerPolicy.DEFAULT_SERVER)); } catch(Exception ignored) {}
        slug=prefs.getString("event","demo");
        getWindow().setStatusBarColor(INK);
        root=column();root.setBackgroundColor(BG);
        root.setOnApplyWindowInsetsListener((v,insets)->{v.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());return insets.consumeSystemWindowInsets();});
        setContentView(root);showHome();
    }
    private int dp(float n){return (int)(getResources().getDisplayMetrics().density*n+.5f);}
    private LinearLayout column(){LinearLayout v=new LinearLayout(this);v.setOrientation(LinearLayout.VERTICAL);v.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);return v;}
    private TextView label(String s,int size,int color,boolean bold){TextView t=new TextView(this);t.setText(s);t.setTextSize(size);t.setTextColor(color);t.setGravity(Gravity.START);if(bold)t.setTypeface(Typeface.DEFAULT,Typeface.BOLD);return t;}
    private GradientDrawable rounded(int color,int radius){GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(radius));return d;}
    private Button action(String s,Runnable r){Button b=new Button(this);b.setText(s);b.setTextSize(14);b.setAllCaps(false);b.setTextColor(TEAL);b.setMinHeight(dp(48));b.setOnClickListener(v->r.run());return b;}
    private void note(String s){Toast.makeText(this,s,Toast.LENGTH_LONG).show();}
    private void addSpace(LinearLayout v,int n){v.addView(new View(this),new LinearLayout.LayoutParams(1,dp(n)));}
    private LinearLayout card(String title,String subtitle,Runnable click){
        LinearLayout c=column();c.setPadding(dp(20),dp(18),dp(20),dp(18));c.setBackground(rounded(Color.WHITE,20));
        c.addView(label(title,19,INK,true));addSpace(c,6);c.addView(label(subtitle,14,MUTED,false));
        c.setMinimumHeight(dp(92));c.setFocusable(true);c.setClickable(true);c.setContentDescription(title+". "+subtitle);
        c.setOnClickListener(v->click.run());LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.bottomMargin=dp(12);c.setLayoutParams(p);return c;
    }
    private void showHome(){
        home=true;if(web!=null){stopCameraTracks();web.onPause();}root.removeAllViews();
        ScrollView scroll=new ScrollView(this);content=column();content.setPadding(dp(22),dp(22),dp(22),dp(12));scroll.addView(content);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        LinearLayout hero=column();hero.setPadding(dp(24),dp(24),dp(24),dp(26));hero.setBackground(rounded(INK,28));
        TextView brand=label("Eventna إيفنتنا",16,0xff70dfc1,true);brand.setLayoutDirection(View.LAYOUT_DIRECTION_LTR);hero.addView(brand);addSpace(hero,20);
        hero.addView(label("حضورك يصنع\nالتجربة.",34,Color.WHITE,true));addSpace(hero,12);
        hero.addView(label("فعاليات حيّة، تفاعل أقرب، وإدارة في مكان واحد.",15,0xffbfd5d8,false));
        content.addView(hero);addSpace(content,22);
        content.addView(label("مساحتك التفاعلية",23,INK,true));addSpace(content,8);
        content.addView(label(server.isEmpty()?"اربط خادم مؤسستك لبدء الاستخدام.":"الخادم: "+Uri.parse(server).getAuthority(),14,MUTED,false));addSpace(content,18);
        if(server.isEmpty())content.addView(card("ربط خادم Eventna إيفنتنا","أدخل عنوان HTTPS الخاص بمؤسستك. لا توجد بيانات عرض أو نتائج مصطنعة.",this::settings));
        content.addView(card("اكتشف الفعاليات","الجهات المشاركة، الخدمات، الاستبيانات والتصويت.",()->open("/","الفعاليات")));
        content.addView(card("بطاقتي ورمز QR","التسجيل في الفعالية والوصول إلى بطاقة الزائر.",()->openEvent("/guest","بطاقة الزائر")));
        content.addView(card("الإدارة والاستوديو","المحتوى، الدعوات وRSVP، الحسابات، التقارير والصلاحيات.",()->open("/admin","Eventna إيفنتنا Studio")));
        content.addView(card("بوابة الدخول","فحص الجاهزية والتحقق من الزوار عبر جهاز مصرح.",()->openEvent("/scan","بوابة الدخول")));
        content.addView(card("شاشة النتائج","عرض التصويت والنتائج التي وافق المنظم على نشرها.",()->{try{ServerPolicy.eventPath(slug,"");open("/live/"+slug,"شاشة النتائج");}catch(Exception e){note(e.getMessage());}}));
        TextView offline=label("دون اتصال: جهّز صفحات الفعالية والجهاز من داخل التطبيق أولًا. أول اتصال وتسجيل الدخول والمزامنة تحتاج الخادم.",13,MUTED,false);content.addView(offline);addSpace(content,16);
        content.addView(label("Android preview · "+BuildConfig.VERSION_NAME,12,MUTED,false));
        LinearLayout nav=new LinearLayout(this);nav.setGravity(Gravity.CENTER);nav.setBackgroundColor(Color.WHITE);
        nav.addView(action("الرئيسية",this::showHome),new LinearLayout.LayoutParams(0,dp(56),1));
        nav.addView(action("الفعاليات",()->open("/","الفعاليات")),new LinearLayout.LayoutParams(0,dp(56),1));
        nav.addView(action("الإعدادات",this::settings),new LinearLayout.LayoutParams(0,dp(56),1));root.addView(nav);
    }
    private void settings(){
        LinearLayout fields=column();fields.setPadding(dp(24),dp(12),dp(24),dp(8));
        fields.addView(label("خادم مؤسستك",18,INK,true));
        EditText url=new EditText(this);url.setSingleLine();url.setHint("https://events.your-domain.com");url.setText(server);url.setInputType(android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_VARIATION_URI);url.setTextDirection(View.TEXT_DIRECTION_LTR);fields.addView(url);
        fields.addView(label("رمز الفعالية للبطاقة والبوابة وشاشة النتائج",14,MUTED,false));
        EditText event=new EditText(this);event.setSingleLine();event.setText(slug);event.setHint("demo");event.setTextDirection(View.TEXT_DIRECTION_LTR);fields.addView(event);
        fields.addView(label("لا تُدخل كلمة المرور في العنوان. تسجيل الدخول يتم داخل واجهة Eventna إيفنتنا. تغيير الخادم يمسح جلسة وبيانات WebView المحلية بعد موافقتك.",13,MUTED,false));
        AlertDialog d=new AlertDialog.Builder(this).setTitle("إعداد Eventna إيفنتنا").setView(fields).setPositiveButton("فحص وحفظ",null).setNegativeButton("إلغاء",null).create();
        d.setOnShowListener(x->d.getButton(-1).setOnClickListener(v->{
            if(checking)return;
            try{
                String candidate=ServerPolicy.normalize(url.getText().toString());String next=event.getText().toString().trim();ServerPolicy.eventPath(next,"");
                Runnable test=()->checkServer(candidate,next,d);
                if(!server.isEmpty()&&!server.equals(candidate))new AlertDialog.Builder(this).setTitle("تغيير الخادم؟").setMessage("زامن العمليات المعلقة أولًا. سيؤدي تغيير الخادم إلى حذف الجلسات والمحتوى المحفوظ محليًا لهذا التطبيق.").setPositiveButton("زامنت بياناتي — تابع",(a,b)->test.run()).setNegativeButton("رجوع",null).show();else test.run();
            }catch(Exception e){url.setError(e.getMessage());}
        }));d.show();
    }
    private void checkServer(String candidate,String event,AlertDialog dialog){
        checking=true;dialog.getButton(-1).setEnabled(false);dialog.getButton(-1).setText("جارٍ الفحص…");
        io.execute(()->{
            String error=null;
            try{
                HttpURLConnection c=(HttpURLConnection)new URL(candidate+"/api/health").openConnection();c.setConnectTimeout(12000);c.setReadTimeout(12000);c.setInstanceFollowRedirects(false);
                try{if(c.getResponseCode()!=200)throw new IOException();JSONObject health=new JSONObject(new String(readBounded(c.getInputStream(),65536),StandardCharsets.UTF_8));if(!health.has("version")||!health.has("api_version")||!health.has("database"))throw new IOException();}finally{c.disconnect();}
            }catch(Exception e){error="تعذر التحقق من خادم Eventna إيفنتنا. تأكد من HTTPS والعنوان والاتصال.";}
            final String result=error;runOnUiThread(()->{
                checking=false;if(isFinishing()||isDestroyed())return;
                if(result!=null){dialog.getButton(-1).setEnabled(true);dialog.getButton(-1).setText("إعادة الفحص");note(result);return;}
                boolean change=!server.isEmpty()&&!server.equals(candidate);
                Runnable save=()->{server=candidate;slug=event;prefs.edit().putString("server",server).putString("event",slug).apply();dialog.dismiss();showHome();note("تم التحقق وحفظ الخادم.");};
                if(change){destroyWeb();WebStorage.getInstance().deleteAllData();CookieManager.getInstance().removeAllCookies(v->{CookieManager.getInstance().flush();save.run();});}else save.run();
            });
        });
    }
    private void openEvent(String suffix,String title){try{open(ServerPolicy.eventPath(slug,suffix),title);}catch(Exception e){note(e.getMessage());}}
    private void open(String path,String title){
        if(server.isEmpty()){settings();return;}
        if(!path.startsWith("/")||path.startsWith("//"))return;
        home=false;currentPath=path;root.removeAllViews();
        LinearLayout toolbar=new LinearLayout(this);toolbar.setGravity(Gravity.CENTER_VERTICAL);toolbar.setPadding(dp(8),dp(4),dp(8),dp(4));toolbar.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);toolbar.setBackgroundColor(Color.WHITE);
        toolbar.addView(action("الرئيسية",this::showHome));webTitle=label(title,15,INK,true);toolbar.addView(webTitle,new LinearLayout.LayoutParams(0,-2,1));
        if(path.endsWith("/scan"))toolbar.addView(action("QR",()->{if(web!=null&&ServerPolicy.sameOrigin(server,web.getUrl()))startActivityForResult(new Intent(this,QrScanActivity.class),QR_SCAN);}));
        toolbar.addView(action("تحديث",()->{if(web!=null)web.reload();}));root.addView(toolbar);
        progress=new ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal);root.addView(progress,new LinearLayout.LayoutParams(-1,dp(3)));
        if(web==null){
            try{createWeb();}catch(RuntimeException error){
                try{destroyWeb();}catch(RuntimeException ignored){web=null;}
                progress.setVisibility(View.GONE);
                LinearLayout recovery=column();recovery.setPadding(dp(24),dp(24),dp(24),dp(24));
                recovery.addView(label("تعذر تشغيل مكوّن عرض الويب في الهاتف.",20,INK,true));
                recovery.addView(label("حدّث مكوّن عرض الويب من متجر جهازك، أو افتح المنصة في المتصفح.",15,MUTED,false));
                recovery.addView(action("فتح المنصة في المتصفح",()->{
                    try{startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(server+path)).addCategory(Intent.CATEGORY_BROWSABLE));}
                    catch(Exception unavailable){note("لا يوجد متصفح متاح على الجهاز.");}
                }));
                root.addView(recovery);return;
            }
        }else{ViewGroup parent=(ViewGroup)web.getParent();if(parent!=null)parent.removeView(web);}
        web.setVisibility(View.VISIBLE);webHolder=column();webHolder.addView(web,new LinearLayout.LayoutParams(-1,-1));root.addView(webHolder,new LinearLayout.LayoutParams(-1,0,1));web.onResume();web.loadUrl(server+path);
    }
    @SuppressWarnings("deprecation") private void createWeb(){
        web=new WebView(this);web.setBackgroundColor(BG);WebSettings s=web.getSettings();
        s.setJavaScriptEnabled(true);s.setDomStorageEnabled(true);s.setAllowFileAccess(false);s.setAllowContentAccess(false);s.setAllowFileAccessFromFileURLs(false);s.setAllowUniversalAccessFromFileURLs(false);s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);s.setGeolocationEnabled(false);s.setSafeBrowsingEnabled(true);s.setMediaPlaybackRequiresUserGesture(true);s.setSupportMultipleWindows(false);s.setJavaScriptCanOpenWindowsAutomatically(false);s.setUserAgentString(s.getUserAgentString()+" EventnaAndroid/"+BuildConfig.VERSION_NAME);
        CookieManager.getInstance().setAcceptCookie(true);CookieManager.getInstance().setAcceptThirdPartyCookies(web,false);
        ServiceWorkerController.getInstance().getServiceWorkerWebSettings().setAllowFileAccess(false);
        ServiceWorkerController.getInstance().getServiceWorkerWebSettings().setAllowContentAccess(false);
        WebView.setWebContentsDebuggingEnabled(false);
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest request){
                String url=request.getUrl().toString();if(ServerPolicy.sameOrigin(server,url))return false;
                if(request.isForMainFrame()&&request.hasGesture()&&"https".equals(request.getUrl().getScheme()))new AlertDialog.Builder(MainActivity.this).setTitle("رابط خارجي").setMessage("سيُفتح في المتصفح خارج جلسة Eventna إيفنتنا.").setPositiveButton("فتح",(d,w)->{try{startActivity(new Intent(Intent.ACTION_VIEW,request.getUrl()).addCategory(Intent.CATEGORY_BROWSABLE));}catch(Exception e){note("لا يوجد متصفح متاح.");}}).setNegativeButton("إلغاء",null).show();return true;
            }
            @Override public void onReceivedSslError(WebView v,android.webkit.SslErrorHandler handler,android.net.http.SslError error){handler.cancel();note("شهادة الاتصال غير موثوقة. لم يتم تجاوزها.");}
            @Override public void onReceivedError(WebView v,WebResourceRequest r,WebResourceError e){if(r.isForMainFrame())showNetworkError();}
            @Override public void onPageFinished(WebView v,String url){CookieManager.getInstance().flush();if(progress!=null)progress.setVisibility(View.GONE);}
        });
        web.setWebChromeClient(new WebChromeClient(){
            @Override public void onProgressChanged(WebView v,int value){if(progress!=null){progress.setVisibility(value==100?View.GONE:View.VISIBLE);progress.setProgress(value);}}
            @Override public boolean onShowFileChooser(WebView v,ValueCallback<Uri[]> callback,FileChooserParams params){
                if(!ServerPolicy.sameOrigin(server,v.getUrl()))return false;if(fileCallback!=null)fileCallback.onReceiveValue(null);fileCallback=callback;
                Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT);i.addCategory(Intent.CATEGORY_OPENABLE);i.setType("*/*");i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE,params.getMode()==FileChooserParams.MODE_OPEN_MULTIPLE);
                try{startActivityForResult(i,FILE_PICK);}catch(Exception e){fileCallback.onReceiveValue(null);fileCallback=null;note("تعذر فتح اختيار الملفات.");}return true;
            }
            @Override public void onPermissionRequest(PermissionRequest request){runOnUiThread(()->{
                if(!ServerPolicy.sameOrigin(server,request.getOrigin().toString())||!ServerPolicy.sameOrigin(server,web.getUrl())||home){request.deny();return;}
                boolean video=false;for(String x:request.getResources())if(PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(x))video=true;
                if(!video){request.deny();return;}if(cameraRequest!=null)cameraRequest.deny();cameraRequest=request;
                if(checkSelfPermission(Manifest.permission.CAMERA)==PackageManager.PERMISSION_GRANTED)grantCamera();else requestPermissions(new String[]{Manifest.permission.CAMERA},CAMERA);
            });}
            @Override public void onPermissionRequestCanceled(PermissionRequest r){if(cameraRequest==r)cameraRequest=null;}
            @Override public boolean onJsPrompt(WebView v,String url,String message,String defaultValue,JsPromptResult result){
                if(message.startsWith("PULSEX_EXPORT:")&&message.length()<MAX_EXPORT*2&&ServerPolicy.sameOrigin(server,url)&&ServerPolicy.sameOrigin(server,v.getUrl())){
                    try{JSONObject j=new JSONObject(message.substring(14));byte[] bytes=Base64.decode(j.getString("base64"),Base64.DEFAULT);if(bytes.length>MAX_EXPORT)throw new IOException();saveDocument(bytes,j.optString("name","pulsex-export"),j.optString("mime","application/octet-stream"));result.confirm("queued");}catch(Exception e){result.cancel();note("تعذر حفظ الملف أو تجاوز الحد المسموح.");}return true;
                }return false;
            }
        });
        web.setDownloadListener((url,agent,disposition,mime,length)->{
            if(home||!ServerPolicy.sameOrigin(server,web.getUrl()))return;
            String name=URLUtil.guessFileName(url,disposition,mime);
            if(url.startsWith("blob:"+server+"/")){
                String js="(async()=>{try{let r=await fetch("+JSONObject.quote(url)+");let b=await r.blob();if(b.size>"+MAX_EXPORT+")throw Error();let f=new FileReader();f.onload=()=>prompt('PULSEX_EXPORT:'+JSON.stringify({name:"+JSONObject.quote(name)+",mime:b.type,base64:String(f.result).split(',')[1]}));f.readAsDataURL(b);}catch(e){alert('تعذر تجهيز الملف للتنزيل.');}})()";
                web.evaluateJavascript(js,null);
            }else if(ServerPolicy.sameOrigin(server,url)){
                final String cookie=CookieManager.getInstance().getCookie(url);io.execute(()->{
                    HttpURLConnection c=null;try{c=(HttpURLConnection)new URL(url).openConnection();c.setConnectTimeout(12000);c.setReadTimeout(20000);c.setInstanceFollowRedirects(false);if(cookie!=null)c.setRequestProperty("Cookie",cookie);if(c.getResponseCode()!=200)throw new IOException();byte[] data=readBounded(c.getInputStream(),MAX_EXPORT);runOnUiThread(()->saveDocument(data,name,mime));}catch(Exception e){runOnUiThread(()->note("تعذر التنزيل. تحقق من الصلاحيات والاتصال وحجم الملف."));}finally{if(c!=null)c.disconnect();}
                });
            }else note("التنزيل متاح من خادم Eventna إيفنتنا الموثوق فقط.");
        });
    }
    private void grantCamera(){if(cameraRequest!=null){if(!home&&web!=null&&ServerPolicy.sameOrigin(server,web.getUrl())&&ServerPolicy.sameOrigin(server,cameraRequest.getOrigin().toString()))cameraRequest.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});else cameraRequest.deny();cameraRequest=null;}}
    @Override public void onRequestPermissionsResult(int r,String[] p,int[] g){super.onRequestPermissionsResult(r,p,g);if(r==CAMERA){if(g.length>0&&g[0]==PackageManager.PERMISSION_GRANTED)grantCamera();else{if(cameraRequest!=null)cameraRequest.deny();cameraRequest=null;note("يمكن استخدام البحث اليدوي أو قارئ QR خارجي دون الكاميرا.");}}}
    private void showNetworkError(){if(home||webHolder==null)return;LinearLayout error=column();error.setPadding(dp(28),dp(38),dp(28),dp(20));error.setBackgroundColor(BG);error.addView(label("الاتصال غير متاح",25,INK,true));addSpace(error,12);error.addView(label("لا توجد استجابة من الخادم لهذه الصفحة. الصفحات والعمليات المجهزة دون اتصال تديرها واجهة Eventna إيفنتنا؛ لا تمسح بيانات التطبيق قبل المزامنة.",16,MUTED,false));error.addView(action("إعادة المحاولة",()->open(currentPath,"Eventna إيفنتنا")));error.addView(action("العودة للرئيسية",this::showHome));webHolder.addView(error,new LinearLayout.LayoutParams(-1,-1));web.setVisibility(View.GONE);}
    private void saveDocument(byte[] data,String name,String mime){
        if(isFinishing()||isDestroyed())return;if(pendingExport!=null){note("أكمل عملية الحفظ الحالية أولًا.");return;}
        pendingExport=data;Intent i=new Intent(Intent.ACTION_CREATE_DOCUMENT);i.addCategory(Intent.CATEGORY_OPENABLE);i.setType(mime==null||mime.isEmpty()?"application/octet-stream":mime);i.putExtra(Intent.EXTRA_TITLE,name.replaceAll("[\\\\/\\r\\n]","_"));
        try{startActivityForResult(i,FILE_SAVE);}catch(Exception e){pendingExport=null;note("تعذر فتح نافذة حفظ الملف.");}
    }
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);
        if(request==QR_SCAN&&result==RESULT_OK&&data!=null&&web!=null&&!home&&ServerPolicy.sameOrigin(server,web.getUrl())&&Uri.parse(web.getUrl()).getPath().endsWith("/scan")){
            String code=data.getStringExtra("qr");if(code!=null&&code.length()<=4096)web.evaluateJavascript("window.dispatchEvent(new CustomEvent('pulsex:native-scan',{detail:"+JSONObject.quote(code)+"}))",null);
        }
        if(request==FILE_PICK&&fileCallback!=null){fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result,data));fileCallback=null;}
        if(request==FILE_SAVE){byte[] bytes=pendingExport;pendingExport=null;if(result==RESULT_OK&&data!=null&&data.getData()!=null&&bytes!=null){Uri uri=data.getData();io.execute(()->{try(OutputStream out=getContentResolver().openOutputStream(uri)){if(out==null)throw new IOException();out.write(bytes);runOnUiThread(()->note("تم حفظ الملف."));}catch(Exception e){runOnUiThread(()->note("تعذر حفظ الملف."));}});}}
    }
    private static byte[] readBounded(InputStream stream,int limit)throws IOException{try(InputStream in=stream;ByteArrayOutputStream out=new ByteArrayOutputStream()){byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1){if(out.size()+n>limit)throw new IOException("FILE_LIMIT");out.write(b,0,n);}return out.toByteArray();}}
    @Override public void onBackPressed(){if(!home&&web!=null&&web.canGoBack())web.goBack();else if(!home)showHome();else super.onBackPressed();}
    private void stopCameraTracks(){web.evaluateJavascript("document.querySelectorAll('video').forEach(v=>{if(v.srcObject&&v.srcObject.getTracks)v.srcObject.getTracks().forEach(t=>t.stop());})",null);}
    @Override protected void onPause(){if(web!=null){stopCameraTracks();web.onPause();}CookieManager.getInstance().flush();super.onPause();}
    @Override protected void onResume(){super.onResume();if(web!=null&&!home)web.onResume();}
    private void destroyWeb(){if(cameraRequest!=null){cameraRequest.deny();cameraRequest=null;}if(fileCallback!=null){fileCallback.onReceiveValue(null);fileCallback=null;}if(web!=null){web.stopLoading();web.clearHistory();web.clearCache(true);ViewGroup p=(ViewGroup)web.getParent();if(p!=null)p.removeView(web);web.destroy();web=null;}}
    @Override protected void onDestroy(){destroyWeb();io.shutdownNow();super.onDestroy();}
}
