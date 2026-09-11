package com.travel.backend.common;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.data.redis.core.ZSetOperations;

import java.time.Duration;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class DistributedStateServiceTest {

    private StringRedisTemplate redis;
    private ValueOperations<String, String> valueOps;
    private ZSetOperations<String, String> zsetOps;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        redis = mock(StringRedisTemplate.class);
        valueOps = mock(ValueOperations.class);
        zsetOps = mock(ZSetOperations.class);
        when(redis.opsForValue()).thenReturn(valueOps);
        when(redis.opsForZSet()).thenReturn(zsetOps);
    }

    @Test
    void localSlidingWindowCountsAndResets() {
        DistributedStateService s = new DistributedStateService(redis, false);
        Duration w = Duration.ofMinutes(15);
        assertEquals(1, s.increment("k", w));
        assertEquals(2, s.increment("k", w));
        assertEquals(2, s.getCount("k", w));
        s.resetCounter("k");
        assertEquals(0, s.getCount("k", w));
    }

    @Test
    void localSlidingWindowExpiresOldEvents() throws Exception {
        DistributedStateService s = new DistributedStateService(redis, false);
        Duration w = Duration.ofMillis(80);
        assertEquals(1, s.increment("k", w));
        Thread.sleep(120);
        // 旧事件应被裁剪
        assertEquals(1, s.increment("k", w));
        assertEquals(1, s.getCount("k", w));
    }

    @Test
    void localTryMarkExclusive() {
        DistributedStateService s = new DistributedStateService(redis, false);
        assertTrue(s.tryMark("lock", Duration.ofMinutes(1)));
        assertFalse(s.tryMark("lock", Duration.ofMinutes(1)));
        s.unmark("lock");
        assertTrue(s.tryMark("lock", Duration.ofMinutes(1)));
    }

    @Test
    void redisPreferredFallsBackWhenRedisDown() {
        when(zsetOps.add(anyString(), anyString(), anyDouble())).thenThrow(new RuntimeException("redis down"));
        when(zsetOps.zCard(anyString())).thenThrow(new RuntimeException("redis down"));
        when(valueOps.setIfAbsent(anyString(), anyString(), any(Duration.class)))
                .thenThrow(new RuntimeException("redis down"));
        DistributedStateService s = new DistributedStateService(redis, true);
        assertEquals(1, s.increment("k", Duration.ofMinutes(1)));
        assertTrue(s.tryMark("m", Duration.ofMinutes(1)));
        assertFalse(s.tryMark("m", Duration.ofMinutes(1)));
    }

    @Test
    void redisPreferredUsesSlidingZSet() {
        when(zsetOps.add(eq("cnt"), anyString(), anyDouble())).thenReturn(true);
        when(zsetOps.zCard("cnt")).thenReturn(3L);
        when(redis.expire(eq("cnt"), any(Duration.class))).thenReturn(true);
        DistributedStateService s = new DistributedStateService(redis, true);
        assertEquals(3, s.increment("cnt", Duration.ofMinutes(1)));
        when(valueOps.setIfAbsent("lk", "1", Duration.ofSeconds(30))).thenReturn(true);
        assertTrue(s.tryMark("lk", Duration.ofSeconds(30)));
    }
}
