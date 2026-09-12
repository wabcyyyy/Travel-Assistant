package com.travel.backend.common;

import org.junit.jupiter.api.Test;
import org.springframework.data.redis.connection.RedisConnection;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.listener.RedisMessageListenerContainer;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 事件通道管理器单测（容器注入 mock，确定性验证启停/重建/断流决策）：
 * - 启动失败不外泄且订阅状态不可信（isRunning 不可信的回归）；
 * - Redis 恢复后 guard 重建订阅（stop + start）；
 * - Redis 失联且有订阅者 → closeAll 促使前端降级轮询。
 * 定时器（@Scheduled）依赖真实时钟不在此测试。
 */
class ItineraryEventChannelManagerTest {

    private final ItinerarySseGateway gateway = new ItinerarySseGateway();
    private final RedisConnectionFactory factory = mock(RedisConnectionFactory.class);
    private final RedisConnection connection = mock(RedisConnection.class);
    private final RedisMessageListenerContainer container = mock(RedisMessageListenerContainer.class);

    private ItineraryEventChannelManager newManager() {
        return new ItineraryEventChannelManager(gateway, factory, container);
    }

    private void redisAlive(boolean alive) {
        if (alive) {
            when(connection.ping()).thenReturn("PONG");
        } else {
            when(connection.ping()).thenThrow(new IllegalStateException("connection closed"));
        }
        when(factory.getConnection()).thenReturn(connection);
    }

    /** onReady 在 Redis 不可达时必须吞掉启动异常（应用启动 resilience 红线）。 */
    @Test
    void onReadySwallowsStartupFailure() {
        ItineraryEventChannelManager manager = newManager();
        doThrow(new IllegalStateException("redis down")).when(container).start();

        manager.onReady();

        // 不抛出即通过；订阅未建立，等待 guard 在 Redis 恢复后重建
        assertFalse(manager.isSubscriptionActive());
    }

    /** 曾启动失败 + Redis 恢复：guard 必须重建订阅（stop 清残留 + start）。 */
    @Test
    void rebuildsSubscriptionOnceRedisRecovers() {
        ItineraryEventChannelManager manager = newManager();
        doThrow(new IllegalStateException("redis down")).when(container).start();
        manager.onReady();
        assertFalse(manager.isSubscriptionActive());

        // Redis 恢复：下一轮 guard 重建订阅成功
        redisAlive(true);
        org.mockito.Mockito.doNothing().when(container).start();
        manager.guard();
        verify(container).stop();
        // onReady 失败的 start 与恢复后的 start 各计一次
        verify(container, org.mockito.Mockito.times(2)).start();
        assertTrue(manager.isSubscriptionActive());
    }

    /** Redis 失联且存在订阅者：guard 断开全部连接（前端据此降级轮询），且自身不抛错。 */
    @Test
    void guardClosesAllStreamsWhenRedisDown() throws IOException {
        SseEmitter emitter = mock(SseEmitter.class);
        gateway.register(7L, emitter);
        redisAlive(false);

        newManager().guard();

        verify(emitter).complete();
        assertFalse(gateway.hasSubscribers());
    }

    /** Redis 健康：即使有订阅者也不断开。 */
    @Test
    void guardKeepsStreamsWhenRedisAlive() throws IOException {
        SseEmitter emitter = mock(SseEmitter.class);
        gateway.register(7L, emitter);
        redisAlive(true);

        newManager().guard();

        verify(emitter, never()).complete();
        assertTrue(gateway.hasSubscribers());
    }

    /** 无订阅者时 Redis 失联无需断流动作。 */
    @Test
    void guardIsSafeWithoutSubscribers() {
        redisAlive(false);

        newManager().guard();

        assertFalse(gateway.hasSubscribers());
    }

    /** closeAll 幂等：注册表清空后再次调用是 no-op。 */
    @Test
    void gatewayCloseAllIsIdempotent() throws IOException {
        SseEmitter emitter = mock(SseEmitter.class);
        gateway.register(8L, emitter);
        gateway.closeAll();
        gateway.closeAll();

        verify(emitter).complete();
        assertFalse(gateway.hasSubscribers());
    }
}
