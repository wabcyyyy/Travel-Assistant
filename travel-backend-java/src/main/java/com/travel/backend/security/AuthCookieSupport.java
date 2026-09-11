package com.travel.backend.security;

import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.Optional;

/**
 * HttpOnly 会话 Cookie 读写。Cookie 不可被 JS 读取，降低 XSS 直接偷 token 的面；
 * 同时仍支持 Authorization Bearer，便于脚本/联调。
 */
@Component
public class AuthCookieSupport {

    public static final String COOKIE_NAME = "TA_AUTH";
    public static final String ATTR_SOURCE = "travel.auth.source";
    public static final String SOURCE_COOKIE = "cookie";
    public static final String SOURCE_BEARER = "bearer";

    private final boolean secure;
    private final long maxAgeSeconds;

    public AuthCookieSupport(
            @Value("${app.auth.cookie-secure:false}") boolean secure,
            @Value("${app.jwt.expire-hours:24}") long expireHours) {
        this.secure = secure;
        this.maxAgeSeconds = Math.max(60, expireHours * 3600L);
    }

    public void writeAuthCookie(HttpServletResponse response, String token) {
        if (token == null || token.isBlank()) {
            return;
        }
        ResponseCookie cookie = ResponseCookie.from(COOKIE_NAME, token)
                .httpOnly(true)
                .secure(secure)
                .path("/")
                // Lax：跨站 POST 不会自动带上 Cookie，配合 Origin 校验
                .sameSite("Lax")
                .maxAge(Duration.ofSeconds(maxAgeSeconds))
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());
    }

    public void clearAuthCookie(HttpServletResponse response) {
        ResponseCookie cookie = ResponseCookie.from(COOKIE_NAME, "")
                .httpOnly(true)
                .secure(secure)
                .path("/")
                .sameSite("Lax")
                .maxAge(Duration.ZERO)
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());
    }

    public Optional<String> readToken(HttpServletRequest request) {
        String auth = request.getHeader(HttpHeaders.AUTHORIZATION);
        if (auth != null && auth.startsWith("Bearer ")) {
            String t = auth.substring(7).trim();
            if (!t.isEmpty()) {
                request.setAttribute(ATTR_SOURCE, SOURCE_BEARER);
                return Optional.of(t);
            }
        }
        Cookie[] cookies = request.getCookies();
        if (cookies != null) {
            for (Cookie c : cookies) {
                if (COOKIE_NAME.equals(c.getName()) && c.getValue() != null && !c.getValue().isBlank()) {
                    request.setAttribute(ATTR_SOURCE, SOURCE_COOKIE);
                    return Optional.of(c.getValue());
                }
            }
        }
        return Optional.empty();
    }
}
