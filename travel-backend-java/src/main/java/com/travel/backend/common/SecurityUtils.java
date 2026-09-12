package com.travel.backend.common;

import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.context.request.RequestAttributes;
import org.springframework.web.context.request.RequestContextHolder;

import java.util.function.Supplier;

public final class SecurityUtils {

    /** 请求内用户 ID 记忆化的 attribute 名（挂在 request 作用域，请求结束自动释放）。 */
    private static final String CACHED_USER_ID_ATTR = SecurityUtils.class.getName() + ".cachedUserId";

    private SecurityUtils() {
    }

    public static String currentUsername() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null || !authentication.isAuthenticated()
                || "anonymousUser".equals(authentication.getPrincipal())) {
            throw new BizException(Result.CODE_UNAUTHORIZED, "未登录");
        }
        return (String) authentication.getPrincipal();
    }

    /**
     * 同一 HTTP 请求内只解析一次用户 ID（J9）：以 request attribute 记忆化 resolver 结果。
     * 一个请求内多次调用 currentUserId() 此前每次都会 getByUsername 查库；principal 只是
     * 用户名，无 JWT/过滤器改动的前提下，用请求级记忆化把 N 次查库降为 1 次。
     * 非 HTTP 上下文（定时任务/异步线程）退化为每次直接解析。
     */
    public static Long cachedUserId(Supplier<Long> resolver) {
        RequestAttributes request = RequestContextHolder.getRequestAttributes();
        if (request == null) {
            return resolver.get();
        }
        Object cached = request.getAttribute(CACHED_USER_ID_ATTR, RequestAttributes.SCOPE_REQUEST);
        if (cached instanceof Long id) {
            return id;
        }
        Long id = resolver.get();
        request.setAttribute(CACHED_USER_ID_ATTR, id, RequestAttributes.SCOPE_REQUEST);
        return id;
    }
}