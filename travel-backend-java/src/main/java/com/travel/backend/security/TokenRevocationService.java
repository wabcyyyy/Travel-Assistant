package com.travel.backend.security;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * JWT 服务端吊销：按 token 哈希写入黑名单，剩余 TTL 覆盖到过期时刻。
 * Redis 不可用时降级为进程内 Map（仅单机演示有效），避免缓存故障拖垮鉴权。
 */
@Service
public class TokenRevocationService {

    private static final Logger log = LoggerFactory.getLogger(TokenRevocationService.class);
    private static final String KEY_PREFIX = "auth:jwt:revoked:";

    private final StringRedisTemplate redisTemplate;
    private final boolean redisPreferred;

    /** Redis 故障时的本机兜底：jti/hash → 过期 epoch 秒 */
    private final Map<String, Long> localBlacklist = new ConcurrentHashMap<>();

    public TokenRevocationService(StringRedisTemplate redisTemplate,
                                  @Value("${app.jwt.revocation-prefer-redis:true}") boolean redisPreferred) {
        this.redisTemplate = redisTemplate;
        this.redisPreferred = redisPreferred;
    }

    public void revoke(String token, long ttlSeconds) {
        if (token == null || token.isBlank() || ttlSeconds <= 0) {
            return;
        }
        String key = hash(token);
        boolean stored = false;
        if (redisPreferred) {
            try {
                redisTemplate.opsForValue().set(KEY_PREFIX + key, "1",
                        java.time.Duration.ofSeconds(ttlSeconds));
                stored = true;
            } catch (Exception ex) {
                log.warn("redis revoke failed, fallback to local: {}", ex.getMessage());
            }
        }
        if (!stored) {
            localBlacklist.put(key, System.currentTimeMillis() / 1000 + ttlSeconds);
        }
    }

    public boolean isRevoked(String token) {
        if (token == null || token.isBlank()) {
            return false;
        }
        String key = hash(token);
        if (redisPreferred) {
            try {
                Boolean hit = redisTemplate.hasKey(KEY_PREFIX + key);
                if (Boolean.TRUE.equals(hit)) {
                    return true;
                }
            } catch (Exception ex) {
                log.debug("redis revoke check failed, fallback to local: {}", ex.getMessage());
            }
        }
        Long exp = localBlacklist.get(key);
        if (exp == null) {
            return false;
        }
        if (exp < System.currentTimeMillis() / 1000) {
            localBlacklist.remove(key);
            return false;
        }
        return true;
    }

    private static String hash(String token) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest(token.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(bytes.length * 2);
            for (byte b : bytes) {
                sb.append(Character.forDigit((b >> 4) & 0xF, 16));
                sb.append(Character.forDigit(b & 0xF, 16));
            }
            return sb.toString();
        } catch (Exception ex) {
            // SHA-256 必存在；若异常则退化为不可逆长度截断（仅兜底）
            return Integer.toHexString(token.hashCode());
        }
    }
}
