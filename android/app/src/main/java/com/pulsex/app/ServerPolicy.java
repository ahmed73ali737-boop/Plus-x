package com.pulsex.app;

import java.net.URI;

/** Pure Java boundary shared by the activity and executable JVM checks. */
public final class ServerPolicy {
    private ServerPolicy() {}
    public static String normalize(String value) {
        try {
            URI u = new URI(value.trim());
            String path = u.getRawPath();
            if (!"https".equalsIgnoreCase(u.getScheme()) || u.getHost() == null
                    || u.getRawUserInfo() != null || u.getRawQuery() != null || u.getRawFragment() != null
                    || (path != null && !path.isEmpty() && !path.equals("/"))
                    || u.getPort() == 0 || u.getPort() > 65535) throw new IllegalArgumentException();
            return new URI("https", null, u.getHost().toLowerCase(java.util.Locale.ROOT),
                    u.getPort() == 443 ? -1 : u.getPort(), null, null, null).toASCIIString();
        } catch (Exception e) { throw new IllegalArgumentException("أدخل عنوان HTTPS للخادم دون مسار أو بيانات دخول."); }
    }
    public static boolean sameOrigin(String server, String target) {
        try {
            URI u = new URI(target);
            if (u.getRawUserInfo() != null || u.getHost() == null) return false;
            return normalize(server).equals(normalize(new URI(u.getScheme(), null, u.getHost(), u.getPort(), null, null, null).toString()));
        } catch (Exception e) { return false; }
    }
    public static String eventPath(String slug, String suffix) {
        if (slug == null || !slug.matches("[a-zA-Z0-9_-]{1,80}"))
            throw new IllegalArgumentException("رمز الفعالية: حروف إنجليزية وأرقام وشرطة فقط.");
        return "/e/" + slug + suffix;
    }
}
