package com.travel.backend.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.travel.backend.common.BizException;
import com.travel.backend.common.DistributedStateService;
import com.travel.backend.common.Result;
import com.travel.backend.dto.LoginRequest;
import com.travel.backend.dto.RegisterRequest;
import com.travel.backend.entity.SysUser;
import com.travel.backend.mapper.SysUserMapper;
import com.travel.backend.security.AuthSessionHolder;
import com.travel.backend.security.JwtUtil;
import com.travel.backend.security.TokenRevocationService;
import com.travel.backend.security.UserSessionService;
import com.travel.backend.service.UserService;
import com.travel.backend.vo.LoginResponse;
import com.travel.backend.vo.UserVO;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.time.Duration;
import java.util.Arrays;
import java.util.Set;
import java.util.stream.Collectors;

@Service
public class UserServiceImpl implements UserService {

    private final SysUserMapper sysUserMapper;
    private final PasswordEncoder passwordEncoder;
    private final JwtUtil jwtUtil;
    private final TokenRevocationService tokenRevocationService;
    private final UserSessionService userSessionService;
    private final DistributedStateService state;

    /** 登录失败：IP+用户名，15 分钟窗口 ≥5 次拒绝。 */
    private static final int MAX_LOGIN_FAILURES = 5;
    private static final Duration LOGIN_WINDOW = Duration.ofMinutes(15);
    /** 注册：同 IP 15 分钟窗口。 */
    private static final int MAX_REGISTER_ATTEMPTS = 5;

    private final Set<String> trustedProxyIps;

    public UserServiceImpl(SysUserMapper sysUserMapper, PasswordEncoder passwordEncoder, JwtUtil jwtUtil,
                           TokenRevocationService tokenRevocationService,
                           UserSessionService userSessionService,
                           DistributedStateService state,
                           @Value("${app.security.trusted-proxies:127.0.0.1,0:0:0:0:0:0:0:1,::1}")
                           String trustedProxies) {
        this.sysUserMapper = sysUserMapper;
        this.passwordEncoder = passwordEncoder;
        this.jwtUtil = jwtUtil;
        this.tokenRevocationService = tokenRevocationService;
        this.userSessionService = userSessionService;
        this.state = state;
        this.trustedProxyIps = Arrays.stream(trustedProxies.split(","))
                .map(String::trim)
                .filter(v -> !v.isEmpty())
                .collect(Collectors.toUnmodifiableSet());
    }

    @Override
    public UserVO register(RegisterRequest request) {
        String ip = clientIp();
        String regKey = "auth:register:" + ip;
        long attempts = state.increment(regKey, LOGIN_WINDOW);
        if (attempts > MAX_REGISTER_ATTEMPTS) {
            throw new BizException(429, "注册过于频繁，请稍后再试");
        }
        Long count = sysUserMapper.selectCount(
                new LambdaQueryWrapper<SysUser>().eq(SysUser::getUsername, request.getUsername()));
        if (count == null || count > 0) {
            throw new BizException(400, "注册失败，请检查用户名或稍后重试");
        }
        if (!isPasswordComplexEnough(request.getPassword())) {
            throw new BizException(400, "密码需同时包含字母和数字");
        }
        SysUser user = new SysUser();
        user.setUsername(request.getUsername());
        user.setPassword(passwordEncoder.encode(request.getPassword()));
        user.setNickname(request.getNickname() == null || request.getNickname().isBlank()
                ? request.getUsername() : request.getNickname());
        user.setStatus(1);
        user.setRole("user");
        try {
            sysUserMapper.insert(user);
        } catch (Exception ex) {
            throw new BizException(400, "注册失败，请检查用户名或稍后重试");
        }
        return toVO(user);
    }

    private static boolean isPasswordComplexEnough(String password) {
        boolean hasLetter = false;
        boolean hasDigit = false;
        for (int i = 0; i < password.length(); i++) {
            char c = password.charAt(i);
            if (Character.isLetter(c)) {
                hasLetter = true;
            } else if (Character.isDigit(c)) {
                hasDigit = true;
            }
        }
        return hasLetter && hasDigit;
    }

    @Override
    public LoginResponse login(LoginRequest request) {
        String throttleKey = "auth:login:fail:" + clientIp() + "|" + request.getUsername();
        long current = state.getCount(throttleKey, LOGIN_WINDOW);
        if (current >= MAX_LOGIN_FAILURES) {
            throw new BizException(429, "登录失败次数过多，请稍后再试");
        }
        SysUser user = sysUserMapper.selectOne(
                new LambdaQueryWrapper<SysUser>().eq(SysUser::getUsername, request.getUsername()));
        if (user == null || !passwordEncoder.matches(request.getPassword(), user.getPassword())) {
            state.increment(throttleKey, LOGIN_WINDOW);
            throw new BizException(400, "用户名或密码错误");
        }
        if (user.getStatus() != null && user.getStatus() == 0) {
            throw new BizException(403, "账号已禁用");
        }
        state.resetCounter(throttleKey);
        String token = jwtUtil.generateToken(user.getUsername());
        try {
            var claims = jwtUtil.parseClaims(token);
            long ttl = jwtUtil.remainingSeconds(claims);
            userSessionService.register(user.getUsername(), claims.getId(), token, ttl);
        } catch (Exception ignored) {
            // 会话登记失败不影响登录；Cookie 仍可用
        }
        // 凭据在 HttpOnly Cookie；body 不回传 JWT
        AuthSessionHolder.set(token);
        return new LoginResponse(toVO(user));
    }

    @Override
    public void logout(String rawToken) {
        String token = normalizeToken(rawToken);
        if (token == null) {
            return;
        }
        try {
            var claims = jwtUtil.parseClaims(token);
            long ttl = jwtUtil.remainingSeconds(claims);
            userSessionService.revokeCurrent(claims.getSubject(), claims.getId(), token, ttl);
        } catch (Exception ex) {
            // 无效/过期 token：登出仍视为成功
        }
    }

    @Override
    public int logoutAll(String username) {
        if (username == null || username.isBlank()) {
            return 0;
        }
        return userSessionService.revokeAll(username);
    }

    private static String normalizeToken(String rawToken) {
        if (rawToken == null || rawToken.isBlank()) {
            return null;
        }
        String token = rawToken.startsWith("Bearer ") ? rawToken.substring(7).trim() : rawToken.trim();
        return token.isEmpty() ? null : token;
    }

    private String clientIp() {
        if (RequestContextHolder.getRequestAttributes() instanceof ServletRequestAttributes attributes) {
            HttpServletRequest servletRequest = attributes.getRequest();
            String remote = servletRequest.getRemoteAddr();
            if (remote != null && trustedProxyIps.contains(remote)) {
                String forwarded = servletRequest.getHeader("X-Forwarded-For");
                if (forwarded != null && !forwarded.isBlank()) {
                    return forwarded.split(",")[0].trim();
                }
            }
            return remote == null ? "unknown" : remote;
        }
        return "unknown";
    }

    @Override
    public UserVO getByUsername(String username) {
        SysUser user = sysUserMapper.selectOne(
                new LambdaQueryWrapper<SysUser>().eq(SysUser::getUsername, username));
        if (user == null) {
            throw new BizException(Result.CODE_UNAUTHORIZED, "用户不存在");
        }
        return toVO(user);
    }

    private UserVO toVO(SysUser user) {
        UserVO vo = new UserVO();
        vo.setId(user.getId());
        vo.setUsername(user.getUsername());
        vo.setNickname(user.getNickname());
        vo.setPhone(user.getPhone());
        vo.setRole(user.getRole());
        return vo;
    }
}
