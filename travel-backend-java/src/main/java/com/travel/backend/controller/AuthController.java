package com.travel.backend.controller;

import com.travel.backend.common.Result;
import com.travel.backend.common.SecurityUtils;
import com.travel.backend.dto.LoginRequest;
import com.travel.backend.dto.RegisterRequest;
import com.travel.backend.security.AuthCookieSupport;
import com.travel.backend.service.UserService;
import com.travel.backend.vo.LoginResponse;
import com.travel.backend.vo.UserVO;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
public class AuthController {

    private final UserService userService;
    private final AuthCookieSupport authCookieSupport;

    public AuthController(UserService userService, AuthCookieSupport authCookieSupport) {
        this.userService = userService;
        this.authCookieSupport = authCookieSupport;
    }

    @PostMapping("/api/auth/register")
    public Result<Void> register(@Valid @RequestBody RegisterRequest request) {
        userService.register(request);
        return Result.ok();
    }

    /**
     * 登录：凭据写入 HttpOnly Cookie；响应体不携带 JWT（降低 XSS 窃取面）。
     */
    @PostMapping("/api/auth/login")
    public Result<LoginResponse> login(@Valid @RequestBody LoginRequest request,
                                       HttpServletResponse response) {
        LoginResponse body = userService.login(request);
        // login 内部已注册会话；此处仅需从请求上下文拿 token 写 Cookie——
        // 由于 body 不再含 token，改为由 UserService 通过 ThreadLocal 或
        // 重新签发？更干净：login 返回后再签发会重复。改为在 login 成功后
        // 从 Cookie 无法拿。实现：UserService.login 仍生成 token 并写会话，
        // 但不放入 body；Auth 侧用 package 方法获取——见 AuthSessionHolder。
        String token = com.travel.backend.security.AuthSessionHolder.poll();
        if (token != null) {
            authCookieSupport.writeAuthCookie(response, token);
        }
        return Result.ok(body);
    }

    /**
     * 登出：吊销当前 Bearer/Cookie 中的 token，并清除 HttpOnly Cookie。
     */
    @PostMapping("/api/auth/logout")
    public Result<Void> logout(HttpServletRequest request, HttpServletResponse response) {
        String fromHeader = request.getHeader("Authorization");
        String token = null;
        if (fromHeader != null && fromHeader.startsWith("Bearer ")) {
            token = fromHeader.substring(7).trim();
        } else {
            token = authCookieSupport.readToken(request).orElse(null);
        }
        userService.logout(token);
        authCookieSupport.clearAuthCookie(response);
        return Result.ok();
    }

    /** 多端登出：吊销当前用户全部已登记会话。 */
    @PostMapping("/api/auth/logout-all")
    public Result<Map<String, Object>> logoutAll(HttpServletRequest request, HttpServletResponse response) {
        String username = SecurityUtils.currentUsername();
        int n = userService.logoutAll(username);
        String fromHeader = request.getHeader("Authorization");
        String token = fromHeader != null && fromHeader.startsWith("Bearer ")
                ? fromHeader.substring(7).trim()
                : authCookieSupport.readToken(request).orElse(null);
        if (token != null) {
            userService.logout(token);
        }
        authCookieSupport.clearAuthCookie(response);
        return Result.ok(Map.of("revoked", n));
    }

    @GetMapping("/api/user/info")
    public Result<UserVO> info() {
        return Result.ok(userService.getByUsername(SecurityUtils.currentUsername()));
    }
}
