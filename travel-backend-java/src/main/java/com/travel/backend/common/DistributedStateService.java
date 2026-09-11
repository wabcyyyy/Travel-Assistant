package com.travel.backend.common;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ZSetOperations;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentLinkedDeque;

/**
 * 分布式状态原语：滑动窗口限速、SETNX 标记/锁。
 * <p>
 * 限速采用 <b>滑动窗口</b>（Redis ZSet / 本地时间戳队列），消除固定窗口在
 * 边界可「双倍突发」的问题。Redis 可用时跨实例共享；故障时降级进程内。
 */
@Service
public class DistributedStateService {

    private static final Logger log = LoggerFactory.getLogger(DistributedStateService.class);
    /** 本地单 key 最多保留的时间戳个数，防异常写入导致无界增长。 */
    private static final int LOCAL_HIT_CAP = 10_000;

    private final StringRedisTemplate redis;
    private final boolean redisPreferred;

    /** 本地滑动窗口：key → 事件时间戳队列（毫秒）。 */
    private final Map<String, ConcurrentLinkedDeque<Long>> localHits = new ConcurrentHashMap<>();
    /** 本地兜底：lock/mark key → 过期 epoch 毫秒 */
    private final Map<String, Long> localMarks = new ConcurrentHashMap<>();

    public DistributedStateService(StringRedisTemplate redis,
                                   @Value("${app.state.prefer-redis:true}") boolean redisPreferred) {
        this.redis = redis;
        this.redisPreferred = redisPreferred;
    }

    // ---------- 滑动窗口限速 ----------

    /**
     * 记录一次访问并返回窗口内事件数（含本次）。
     * 窗口语义：now-window &lt; t ≤ now。
     */
    public long increment(String key, Duration window) {
        long windowMillis = window.toMillis();
        if (redisPreferred) {
            try {
                return redisSlidingHit(key, windowMillis);
            } catch (Exception ex) {
                log.warn("redis sliding-window failed, local fallback: {}", ex.getMessage());
            }
        }
        return localSlidingHit(key, windowMillis);
    }

    /** 读窗口内计数（不记入本次访问）。 */
    public long getCount(String key, Duration window) {
        long windowMillis = window.toMillis();
        if (redisPreferred) {
            try {
                return redisSlidingCount(key, windowMillis);
            } catch (Exception ex) {
                log.debug("redis sliding count failed: {}", ex.getMessage());
            }
        }
        return localSlidingCount(key, windowMillis);
    }

    /** 兼容旧调用：无窗口参数时无法裁剪，仅作别名请使用 {@link #getCount(String, Duration)}。 */
    public long getCount(String key) {
        // 无法得知窗口时返回本地队列长度（未裁剪）；生产路径应传 window。
        ConcurrentLinkedDeque<Long> q = localHits.get(key);
        return q == null ? 0 : q.size();
    }

    public void resetCounter(String key) {
        if (redisPreferred) {
            try {
                redis.delete(key);
            } catch (Exception ex) {
                log.debug("redis del failed: {}", ex.getMessage());
            }
        }
        localHits.remove(key);
    }

    public long localCounterPeek(String key) {
        return getCount(key);
    }

    private long redisSlidingHit(String key, long windowMillis) {
        long now = System.currentTimeMillis();
        long min = now - windowMillis;
        ZSetOperations<String, String> zset = redis.opsForZSet();
        // member 用 now + 随机后缀，避免同毫秒多次 hit 被 ZSet 去重
        String member = now + ":" + Thread.currentThread().getId() + ":" + System.nanoTime() % 1_000_000;
        zset.add(key, member, now);
        zset.removeRangeByScore(key, 0, min);
        redis.expire(key, Duration.ofMillis(windowMillis + 1000));
        Long size = zset.zCard(key);
        return size == null ? 1L : size;
    }

    private long redisSlidingCount(String key, long windowMillis) {
        long now = System.currentTimeMillis();
        long min = now - windowMillis;
        ZSetOperations<String, String> zset = redis.opsForZSet();
        zset.removeRangeByScore(key, 0, min);
        Long size = zset.zCard(key);
        return size == null ? 0L : size;
    }

    private long localSlidingHit(String key, long windowMillis) {
        long now = System.currentTimeMillis();
        ConcurrentLinkedDeque<Long> q =
                localHits.computeIfAbsent(key, k -> new ConcurrentLinkedDeque<>());
        synchronized (q) {
            prune(q, now, windowMillis);
            q.addLast(now);
            while (q.size() > LOCAL_HIT_CAP) {
                q.pollFirst();
            }
            return q.size();
        }
    }

    private long localSlidingCount(String key, long windowMillis) {
        ConcurrentLinkedDeque<Long> q = localHits.get(key);
        if (q == null) {
            return 0L;
        }
        synchronized (q) {
            prune(q, System.currentTimeMillis(), windowMillis);
            return q.size();
        }
    }

    private static void prune(ConcurrentLinkedDeque<Long> q, long now, long windowMillis) {
        long min = now - windowMillis;
        while (!q.isEmpty() && q.peekFirst() != null && q.peekFirst() <= min) {
            q.pollFirst();
        }
    }

    // ---------- SETNX 标记 / 锁 ----------

    /** 尝试占用标记（SET key 1 NX EX）。已存在且未过期则返回 false。 */
    public boolean tryMark(String key, Duration ttl) {
        if (redisPreferred) {
            try {
                Boolean ok = redis.opsForValue().setIfAbsent(key, "1", ttl);
                if (ok != null) {
                    return ok;
                }
            } catch (Exception ex) {
                log.warn("redis setnx failed, local fallback: {}", ex.getMessage());
            }
        }
        long exp = System.currentTimeMillis() + ttl.toMillis();
        Long prev = localMarks.putIfAbsent(key, exp);
        if (prev == null) {
            return true;
        }
        if (prev < System.currentTimeMillis()) {
            localMarks.put(key, exp);
            return true;
        }
        return false;
    }

    public void unmark(String key) {
        if (redisPreferred) {
            try {
                redis.delete(key);
            } catch (Exception ex) {
                log.debug("redis unmark failed: {}", ex.getMessage());
            }
        }
        localMarks.remove(key);
    }

    public boolean isMarked(String key) {
        if (redisPreferred) {
            try {
                return Boolean.TRUE.equals(redis.hasKey(key));
            } catch (Exception ex) {
                log.debug("redis hasKey failed: {}", ex.getMessage());
            }
        }
        Long exp = localMarks.get(key);
        if (exp == null) {
            return false;
        }
        if (exp < System.currentTimeMillis()) {
            localMarks.remove(key);
            return false;
        }
        return true;
    }

    /** 测试用：清空本地兜底状态（不影响 Redis）。 */
    public void clearLocal() {
        localHits.clear();
        localMarks.clear();
    }
}
