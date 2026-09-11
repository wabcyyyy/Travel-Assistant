package com.travel.backend.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

/**
 * Cookie 会话的 CSRF 缓解：写方法 + Cookie 鉴权时校验 Origin 白名单。
 * Bearer 请求不受影响（跨站不会自动附带 Authorization 头）。
 * 需挂载在 JwtAuthenticationFilter 之后。
 */
@Component
public class CookieOriginFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(CookieOriginFilter.class);

    private final Set<String> allowedOrigins;

    public CookieOriginFilter(
            @Value("${app.cors.allowed-origins:http://localhost:5173,http://127.0.0.1:5173}")
            String allowedOrigins) {
        Set<String> set = new HashSet<>();
        for (String o : allowedOrigins.split(",")) {
            String v = o.trim();
            if (!v.isEmpty()) {
                set.add(v);
            }
        }
        this.allowedOrigins = set;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        if (isMutating(request.getMethod()) && isAuthenticatedCookie(request)) {
            String origin = request.getHeader("Origin");
            if (origin != null && !origin.isBlank() && !allowedOrigins.contains(origin)) {
                log.warn("cookie auth origin rejected: {}", origin);
                response.setStatus(HttpServletResponse.SC_FORBIDDEN);
                return;
            }
        }
        filterChain.doFilter(request, response);
    }

    private static boolean isMutating(String method) {
        String m = method == null ? "" : method.toUpperCase(Locale.ROOT);
        return "POST".equals(m) || "PUT".equals(m) || "DELETE".equals(m) || "PATCH".equals(m);
    }

    private static boolean isAuthenticatedCookie(HttpServletRequest request) {
        if (!AuthCookieSupport.SOURCE_COOKIE.equals(request.getAttribute(AuthCookieSupport.ATTR_SOURCE))) {
            return false;
        }
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        return auth != null && auth.isAuthenticated() && !"anonymousUser".equals(auth.getPrincipal());
    }
}
