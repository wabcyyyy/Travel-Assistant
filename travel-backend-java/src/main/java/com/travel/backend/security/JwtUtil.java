package com.travel.backend.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.security.SecureRandom;

@Component
public class JwtUtil {

    private static final Logger log = LoggerFactory.getLogger(JwtUtil.class);

    private final SecretKey key;
    private final long expireMillis;

    public JwtUtil(@Value("${app.jwt.secret}") String secret,
                   @Value("${app.jwt.expire-hours:24}") long expireHours) {
        String effectiveSecret = secret;
        if (effectiveSecret == null || effectiveSecret.isBlank()) {
            byte[] randomSecret = new byte[64];
            new SecureRandom().nextBytes(randomSecret);
            effectiveSecret = java.util.Base64.getEncoder().encodeToString(randomSecret);
            log.warn("JWT_SECRET is not configured; using an ephemeral key. Existing sessions will expire after restart.");
        }
        this.key = Keys.hmacShaKeyFor(effectiveSecret.getBytes(StandardCharsets.UTF_8));
        this.expireMillis = expireHours * 3600_000L;
    }

    public String generateToken(String username) {
        Date now = new Date();
        return Jwts.builder()
                .subject(username)
                .issuedAt(now)
                .expiration(new Date(now.getTime() + expireMillis))
                .signWith(key)
                .compact();
    }

    public String parseUsername(String token) {
        Claims claims = Jwts.parser()
                .verifyWith(key)
                .build()
                .parseSignedClaims(token)
                .getPayload();
        return claims.getSubject();
    }
}
