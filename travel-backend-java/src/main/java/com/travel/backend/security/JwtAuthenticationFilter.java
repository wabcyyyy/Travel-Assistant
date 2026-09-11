package com.travel.backend.security;

import com.travel.backend.entity.SysUser;
import com.travel.backend.mapper.SysUserMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;
import java.util.Optional;

/**
 * 鉴权过滤器：Bearer 头或 HttpOnly Cookie（TA_AUTH）二选一；
 * 吊销黑名单与用户状态回查对两种通道一致生效。
 */
@Component
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(JwtAuthenticationFilter.class);
    private static final String ROLE_ADMIN = "admin";

    private final JwtUtil jwtUtil;
    private final SysUserMapper sysUserMapper;
    private final TokenRevocationService tokenRevocationService;
    private final AuthCookieSupport authCookieSupport;

    public JwtAuthenticationFilter(JwtUtil jwtUtil, SysUserMapper sysUserMapper,
                                   TokenRevocationService tokenRevocationService,
                                   AuthCookieSupport authCookieSupport) {
        this.jwtUtil = jwtUtil;
        this.sysUserMapper = sysUserMapper;
        this.tokenRevocationService = tokenRevocationService;
        this.authCookieSupport = authCookieSupport;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        Optional<String> maybe = authCookieSupport.readToken(request);
        if (maybe.isPresent()) {
            String token = maybe.get();
            try {
                if (!tokenRevocationService.isRevoked(token)) {
                    String username = jwtUtil.parseUsername(token);
                    SysUser user = sysUserMapper.selectOne(
                            new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<SysUser>()
                                    .eq(SysUser::getUsername, username));
                    if (user != null && (user.getStatus() == null || user.getStatus() == 1)) {
                        boolean isAdmin = ROLE_ADMIN.equals(user.getRole());
                        UsernamePasswordAuthenticationToken authentication =
                                new UsernamePasswordAuthenticationToken(username, null,
                                        List.of(new SimpleGrantedAuthority(isAdmin ? "ROLE_ADMIN" : "ROLE_USER")));
                        SecurityContextHolder.getContext().setAuthentication(authentication);
                    }
                } else {
                    log.debug("jwt token revoked");
                }
            } catch (Exception e) {
                log.debug("invalid jwt token: {}", e.getMessage());
            }
        }
        filterChain.doFilter(request, response);
    }
}
