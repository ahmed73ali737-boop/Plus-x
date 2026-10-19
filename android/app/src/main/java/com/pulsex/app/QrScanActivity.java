package com.pulsex.app;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.hardware.Camera;
import android.os.Bundle;
import android.view.*;
import android.widget.*;
import com.google.zxing.*;
import com.google.zxing.common.HybridBinarizer;
import com.google.zxing.qrcode.QRCodeReader;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/** Local camera decoder only. A decoded code never authorizes entry. */
@SuppressWarnings("deprecation")
public final class QrScanActivity extends Activity implements SurfaceHolder.Callback, Camera.PreviewCallback {
    private Camera camera;
    private SurfaceView preview;
    private TextView status;
    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    private final AtomicBoolean decoding=new AtomicBoolean(false);
    private boolean finished=false;
    private long lastFrame=0;
    @Override public void onCreate(Bundle state){
        super.onCreate(state);
        LinearLayout layout=new LinearLayout(this);layout.setOrientation(LinearLayout.VERTICAL);layout.setBackgroundColor(0xff102c34);layout.setPadding(16,40,16,24);layout.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
        layout.setOnApplyWindowInsetsListener((v,insets)->{int pad=(int)(16*getResources().getDisplayMetrics().density);v.setPadding(pad+insets.getSystemWindowInsetLeft(),pad+insets.getSystemWindowInsetTop(),pad+insets.getSystemWindowInsetRight(),pad+insets.getSystemWindowInsetBottom());return insets.consumeSystemWindowInsets();});
        TextView title=new TextView(this);title.setText("امسح رمز الزائر");title.setTextColor(Color.WHITE);title.setTextSize(25);layout.addView(title);
        status=new TextView(this);status.setText("ضع رمز QR أمام الكاميرا. التحقق من الصلاحية يتم في بوابة الفعالية بعد القراءة.");status.setTextColor(0xffbfe3dc);status.setTextSize(16);status.setPadding(0,12,0,20);layout.addView(status);
        preview=new SurfaceView(this);layout.addView(preview,new LinearLayout.LayoutParams(-1,0,1));preview.getHolder().addCallback(this);
        Button cancel=new Button(this);cancel.setText("إلغاء والعودة للبوابة");cancel.setOnClickListener(v->finish());layout.addView(cancel);setContentView(layout);
        if(checkSelfPermission(Manifest.permission.CAMERA)!=PackageManager.PERMISSION_GRANTED)requestPermissions(new String[]{Manifest.permission.CAMERA},1);
    }
    @Override public void surfaceCreated(SurfaceHolder holder){startCamera();}
    private void startCamera(){
        if(camera!=null||finished||!preview.getHolder().getSurface().isValid()||checkSelfPermission(Manifest.permission.CAMERA)!=PackageManager.PERMISSION_GRANTED)return;
        try{
            int chosen=-1;Camera.CameraInfo info=new Camera.CameraInfo();
            for(int i=0;i<Camera.getNumberOfCameras();i++){Camera.getCameraInfo(i,info);if(info.facing==Camera.CameraInfo.CAMERA_FACING_BACK){chosen=i;break;}}
            if(chosen<0)throw new IllegalStateException();camera=Camera.open(chosen);Camera.getCameraInfo(chosen,info);
            int rotation=getWindowManager().getDefaultDisplay().getRotation()*90;
            camera.setDisplayOrientation((info.orientation-rotation+360)%360);
            Camera.Parameters p=camera.getParameters();
            Camera.Size selected=p.getPreviewSize();
            for(Camera.Size size:p.getSupportedPreviewSizes())if(size.width<=1280&&size.width>=640&&size.width*size.height<selected.width*selected.height)selected=size;
            p.setPreviewSize(selected.width,selected.height);
            if(p.getSupportedFocusModes().contains(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE))p.setFocusMode(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE);
            camera.setParameters(p);camera.setPreviewDisplay(preview.getHolder());camera.setPreviewCallback(this);camera.startPreview();
        }catch(Exception e){release();status.setText("تعذر فتح الكاميرا. ارجع للبوابة واستخدم الإدخال اليدوي أو قارئًا خارجيًا.");}
    }
    @Override public void onPreviewFrame(byte[] data,Camera source){
        long now=android.os.SystemClock.elapsedRealtime();if(finished||now-lastFrame<300||!decoding.compareAndSet(false,true))return;lastFrame=now;
        Camera.Size size=source.getParameters().getPreviewSize();byte[] frame=data.clone();
        worker.execute(()->{
            try{
                LuminanceSource image=new PlanarYUVLuminanceSource(frame,size.width,size.height,0,0,size.width,size.height,false);
                Result result=new QRCodeReader().decode(new BinaryBitmap(new HybridBinarizer(image)));
                String value=result.getText();
                if(value!=null&&value.length()<=4096)runOnUiThread(()->{if(!finished){finished=true;setResult(RESULT_OK,new Intent().putExtra("qr",value));release();finish();}});
            }catch(Exception ignored){}finally{decoding.set(false);}
        });
    }
    @Override public void surfaceChanged(SurfaceHolder h,int format,int width,int height){}
    @Override public void surfaceDestroyed(SurfaceHolder h){release();}
    private void release(){if(camera!=null){camera.setPreviewCallback(null);camera.stopPreview();camera.release();camera=null;}}
    @Override public void onRequestPermissionsResult(int r,String[] p,int[] g){super.onRequestPermissionsResult(r,p,g);if(r==1&&g.length>0&&g[0]==PackageManager.PERMISSION_GRANTED)startCamera();else status.setText("لم يُمنح إذن الكاميرا. يمكنك الرجوع واستخدام البحث اليدوي.");}
    @Override protected void onPause(){release();super.onPause();}
    @Override protected void onResume(){super.onResume();if(preview!=null)startCamera();}
    @Override protected void onDestroy(){finished=true;release();worker.shutdownNow();super.onDestroy();}
}
