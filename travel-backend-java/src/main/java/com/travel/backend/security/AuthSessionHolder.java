package com.travel.backend.security;

/**
 * 登录成功后、写 Cookie 前传递 JWT 的线程局部。
 * body 不再回传 token，避免 XSS 读响应体；Cookie 由 AuthController 写入。
 */
public final class AuthSessionHolder {

    private static final ThreadLocal<String> TOKEN = new ThreadLocal<>();

    private AuthSessionHolder() {
    }

    public static void set(String token) {
        TOKEN.set(token);
    }

    public static String poll() {
        String t = TOKEN.get();
        TOKEN.remove();
        return t;
    }

    public static void clear() {
        TOKEN.remove();
    }
}
