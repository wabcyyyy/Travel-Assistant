package com.travel.backend.security;

import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class TokenRevocationServiceTest {

    @Test
    void localFallbackRevokesAndExpires() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        when(redis.opsForValue()).thenThrow(new RuntimeException("redis down"));
        when(redis.hasKey(anyString())).thenThrow(new RuntimeException("redis down"));
        TokenRevocationService service = new TokenRevocationService(redis, true);

        String token = "header.payload.signature";
        service.revoke(token, 60);
        assertTrue(service.isRevoked(token));
        assertFalse(service.isRevoked("other-token"));
    }

    @Test
    void skipWhenTtlZero() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        TokenRevocationService service = new TokenRevocationService(redis, true);
        service.revoke("t", 0);
        assertFalse(service.isRevoked("t"));
    }
}
