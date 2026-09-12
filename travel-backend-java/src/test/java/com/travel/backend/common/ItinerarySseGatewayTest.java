package com.travel.backend.common;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

/**
 * SSE 网关单测（不依赖 Redis/Servlet）：注册/广播/坏连接清理/超限拒绝。
 * 心跳不单独测试：@Scheduled(fixedRate) 依赖真实调度与时钟，单测不触发，
 * 且其广播行为与 broadcast 完全同路径（sendOrCleanup），已被下列用例覆盖。
 */
class ItinerarySseGatewayTest {

    private final ItinerarySseGateway gateway = new ItinerarySseGateway();

    /** 广播：注册两个 emitter 后注入一条 Redis 消息，两者都收到。 */
    @Test
    void broadcastForwardsMessageToAllSubscribers() throws Exception {
        SseEmitter first = mock(SseEmitter.class);
        SseEmitter second = mock(SseEmitter.class);
        gateway.register(1L, first);
        gateway.register(1L, second);

        gateway.onRedisMessage("gen:events:1", "{\"type\":\"day_start\",\"seq\":1}");

        verify(first, times(1)).send(any(SseEmitter.SseEventBuilder.class));
        verify(second, times(1)).send(any(SseEmitter.SseEventBuilder.class));
    }

    /** 非法 channel 不抛异常、不广播（防御性解析）。 */
    @Test
    void ignoresUnexpectedChannel() throws Exception {
        SseEmitter emitter = mock(SseEmitter.class);
        gateway.register(1L, emitter);

        gateway.onRedisMessage("other:channel", "{}");
        gateway.onRedisMessage("gen:events:not-a-number", "{}");

        verify(emitter, never()).send(any(SseEmitter.SseEventBuilder.class));
    }

    /** 发送抛异常的 emitter 被移除并 complete：后续广播不再触达死连接。 */
    @Test
    void brokenEmitterIsRemovedAfterSendFailure() throws Exception {
        SseEmitter broken = mock(SseEmitter.class);
        SseEmitter healthy = mock(SseEmitter.class);
        doThrow(new IOException("client gone")).when(broken).send(any(SseEmitter.SseEventBuilder.class));
        gateway.register(2L, broken);
        gateway.register(2L, healthy);

        gateway.onRedisMessage("gen:events:2", "{}");
        gateway.onRedisMessage("gen:events:2", "{}");

        verify(broken).complete();
        verify(healthy, times(2)).send(any(SseEmitter.SseEventBuilder.class));
    }

    /** 同一行程最多 5 个并发 emitter，第 6 个收到上限提示后立即 complete，不再进入广播列表。 */
    @Test
    void rejectsSixthEmitterForSameItinerary() throws Exception {
        for (int i = 0; i < 5; i++) {
            gateway.register(3L, mock(SseEmitter.class));
        }
        SseEmitter sixth = mock(SseEmitter.class);

        gateway.register(3L, sixth);

        // 超限：先发一条 TOO_MANY_CONNECTIONS 提示再 complete
        verify(sixth).complete();
        verify(sixth, times(1)).send(any(SseEmitter.SseEventBuilder.class));
        // 后续广播只触达前 5 个连接，被拒连接不再收到任何事件
        gateway.onRedisMessage("gen:events:3", "{}");
        verify(sixth, times(1)).send(any(SseEmitter.SseEventBuilder.class));
    }

    /** 超限提示信封先于 complete 发出，携带 TOO_MANY_CONNECTIONS 错误码。 */
    @Test
    void limitNoticeCarriesTooManyConnectionsCode() throws Exception {
        for (int i = 0; i < 5; i++) {
            gateway.register(4L, mock(SseEmitter.class));
        }
        SseEmitter sixth = mock(SseEmitter.class);
        gateway.register(4L, sixth);

        ArgumentCaptor<SseEmitter.SseEventBuilder> sent = ArgumentCaptor.forClass(SseEmitter.SseEventBuilder.class);
        verify(sixth).send(sent.capture());
        // 事件可能拆成多个 DataWithMediaType 分片（媒体类型声明 + 数据本体），拼齐后断言错误码
        StringBuilder text = new StringBuilder();
        sent.getValue().build().forEach(data -> text.append(data.getData()));
        assertTrue(text.toString().contains("TOO_MANY_CONNECTIONS"), "超限提示应通过 error 信封送达");
    }

    /** 不同行程的连接互不干扰：广播 4 号行程不影响 5 号。 */
    @Test
    void differentItinerariesAreIsolated() throws Exception {
        SseEmitter onFourth = mock(SseEmitter.class);
        SseEmitter onFifth = mock(SseEmitter.class);
        gateway.register(4L, onFourth);
        gateway.register(5L, onFifth);

        gateway.onRedisMessage("gen:events:4", "{}");

        verify(onFourth, times(1)).send(any(SseEmitter.SseEventBuilder.class));
        verify(onFifth, never()).send(any(SseEmitter.SseEventBuilder.class));
    }

    /** 连接完成回调触发清理：onCompletion 后广播不再触达该连接（注册表不泄漏）。 */
    @Test
    void cleanupHappensOnCompletionCallback() throws Exception {
        SseEmitter emitter = mock(SseEmitter.class);
        gateway.register(6L, emitter);
        ArgumentCaptor<Runnable> cleanup = ArgumentCaptor.forClass(Runnable.class);
        verify(emitter).onCompletion(cleanup.capture());

        cleanup.getValue().run();
        gateway.onRedisMessage("gen:events:6", "{}");

        verify(emitter, never()).send(any(SseEmitter.SseEventBuilder.class));
    }

    /** subscribe 走默认构造：返回的 emitter 已注册（广播可达）。 */
    @Test
    void subscribeRegistersReturnedEmitter() {
        SseEmitter emitter = gateway.subscribe(7L);

        assertEquals(0L, emitter.getTimeout(), "timeout=0 表示连接不超时，由断连回调清理");
    }
}
