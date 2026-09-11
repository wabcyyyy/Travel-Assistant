package com.travel.backend.security;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 多端会话：username → 活跃 jti 集合。
 * <ul>
 *   <li>登录：注册 jti，TTL 与 token 一致</li>
 *   <li>logout：吊销当前 token（TokenRevocationService）并移除 jti</li>
 *   <li>logoutAll：吊销该用户全部已登记 jti（按 hash 存的 token 无法反查，
 *       因此额外维护 jti→token 哈希索引；无 Redis 时仅清本地集合）</li>
 * </ul>
 */
@Service
public class UserSessionService {

    private static final Logger log = LoggerFactory.getLogger(UserSessionService.class);
    private static final String PREFIX = "auth:sess:";

    private final StringRedisTemplate redis;
    private final TokenRevocationService revocation;
    private final boolean redisPreferred;

    /** 本地兜底：username → jti 集合；jti → token 原文（仅内存，进程内会话）。 */
    private final Map<String, Set<String>> localSessions = new ConcurrentHashMap<>();
    private final Map<String, String> localJtiToToken = new ConcurrentHashMap<>();

    public UserSessionService(StringRedisTemplate redis, TokenRevocationService revocation,
                              @org.springframework.beans.factory.annotation.Value("${app.state.prefer-redis:true}")
                              boolean redisPreferred) {
        this.redis = redis;
        this.revocation = revocation;
        this.redisPreferred = redisPreferred;
    }

    public void register(String username, String jti, String token, long ttlSeconds) {
        if (username == null || jti == null || token == null || ttlSeconds <= 0) {
            return;
        }
        if (redisPreferred) {
            try {
                String key = PREFIX + username;
                redis.opsForSet().add(key, jti);
                redis.expire(key, Duration.ofSeconds(ttlSeconds));
                redis.opsForValue().set(PREFIX + "tok:" + jti, token, Duration.ofSeconds(ttlSeconds));
                return;
            } catch (Exception ex) {
                log.warn("session register redis failed, local fallback: {}", ex.getMessage());
            }
        }
        localSessions.computeIfAbsent(username, k -> ConcurrentHashMap.newKeySet()).add(jti);
        localJtiToToken.put(jti, token);
    }

    /** 登出当前 token：黑名单 + 从会话集合移除 jti。 */
    public void revokeCurrent(String username, String jti, String token, long ttlSeconds) {
        revocation.revoke(token, ttlSeconds);
        removeJti(username, jti);
    }

    /** 登出该用户全部会话。 */
    public int revokeAll(String username) {
        int n = 0;
        if (redisPreferred) {
            try {
                String key = PREFIX + username;
                Set<String> jtis = redis.opsForSet().members(key);
                if (jtis != null) {
                    for (String jti : jtis) {
                        String tok = redis.opsForValue().get(PREFIX + "tok:" + jti);
                        if (tok != null) {
                            // 尽量按剩余寿命写入黑名单；拿不到 claims 时用 1 天兜底
                            revocation.revoke(tok, 86_400);
                            n++;
                        }
                        redis.delete(PREFIX + "tok:" + jti);
                    }
                }
                redis.delete(key);
                return n;
            } catch (Exception ex) {
                log.warn("logout-all redis failed: {}", ex.getMessage());
            }
        }
        Set<String> jtis = localSessions.remove(username);
        if (jtis != null) {
            for (String jti : jtis) {
                String tok = localJtiToToken.remove(jti);
                if (tok != null) {
                    revocation.revoke(tok, 86_400);
                    n++;
                }
            }
        }
        return n;
    }

    public List<String> listJtis(String username) {
        if (redisPreferred) {
            try {
                Set<String> set = redis.opsForSet().members(PREFIX + username);
                return set == null ? List.of() : new ArrayList<>(set);
            } catch (Exception ex) {
                log.debug("list sessions redis failed: {}", ex.getMessage());
            }
        }
        Set<String> set = localSessions.get(username);
        return set == null ? List.of() : new ArrayList<>(set);
    }

    private void removeJti(String username, String jti) {
        if (username == null || jti == null) {
            return;
        }
        if (redisPreferred) {
            try {
                redis.opsForSet().remove(PREFIX + username, jti);
                redis.delete(PREFIX + "tok:" + jti);
                return;
            } catch (Exception ex) {
                log.debug("remove jti redis failed: {}", ex.getMessage());
            }
        }
        Set<String> set = localSessions.get(username);
        if (set != null) {
            set.remove(jti);
        }
        localJtiToToken.remove(jti);
    }
}
