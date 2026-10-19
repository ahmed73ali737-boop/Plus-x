import com.pulsex.app.ServerPolicy;
public final class ServerPolicyCheck {
    public static void main(String[] args) {
        int count = 0;
        for (String s : new String[]{"http://host", "https://user:pass@host", "https://host/path", "https://host?token=x", "https://host#x", "file:///x", "javascript:alert(1)", "https://host:0", "https://host:70000", "https://host\\@evil.test"}) {
            try { ServerPolicy.normalize(s); throw new AssertionError(s); } catch (IllegalArgumentException expected) { count++; }
        }
        if (!ServerPolicy.normalize(" https://EXAMPLE.com:443/ ").equals("https://example.com")) throw new AssertionError(); count++;
        if (!ServerPolicy.sameOrigin("https://example.com", "https://example.com/admin?a=1")) throw new AssertionError(); count++;
        for (String t : new String[]{"https://example.com.evil.test", "https://example.com@evil.test", "http://example.com", "https://example.com:444", "data:text/html,Hi", "file:///etc/passwd"}) {
            if (ServerPolicy.sameOrigin("https://example.com",t)) throw new AssertionError(t); count++;
        }
        if (!ServerPolicy.eventPath("demo-01", "/scan").equals("/e/demo-01/scan")) throw new AssertionError(); count++;
        for (String slug : new String[]{"../admin", "", "demo?x=y", "a/b", "demo#token"}) {
            try { ServerPolicy.eventPath(slug, "/guest"); throw new AssertionError(slug); } catch (IllegalArgumentException expected) { count++; }
        }
        System.out.println("PASS ServerPolicy " + count + " checks");
    }
}
