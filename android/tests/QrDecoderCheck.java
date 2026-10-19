import com.google.zxing.*;
import com.google.zxing.common.*;
import com.google.zxing.qrcode.*;
public final class QrDecoderCheck {
    public static void main(String[] args) throws Exception {
        String value="https://events.example.test/e/demo/guest/G-000123?pass=opaque-test";
        BitMatrix qr=new QRCodeWriter().encode(value,BarcodeFormat.QR_CODE,400,400);
        int[] pixels=new int[400*400];
        for(int y=0;y<400;y++)for(int x=0;x<400;x++)pixels[y*400+x]=qr.get(x,y)?0xff000000:0xffffffff;
        Result decoded=new QRCodeReader().decode(new BinaryBitmap(new HybridBinarizer(new RGBLuminanceSource(400,400,pixels))));
        if(!value.equals(decoded.getText()))throw new AssertionError("QR roundtrip mismatch");
        java.util.Arrays.fill(pixels,0xffffffff);
        try{new QRCodeReader().decode(new BinaryBitmap(new HybridBinarizer(new RGBLuminanceSource(400,400,pixels))));throw new AssertionError("Blank image accepted");}catch(NotFoundException expected){}
        System.out.println("PASS QR decode roundtrip and blank-image rejection; camera hardware NOT tested");
    }
}
