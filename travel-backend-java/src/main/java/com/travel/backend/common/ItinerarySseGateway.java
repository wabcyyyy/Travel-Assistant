package com.travel.backend.common;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * 生成进度 SSE 网关：订阅 Redis channel {@code gen:events:{itineraryId}}，
 * 把事件原文转发给订阅同一行程的所有浏览器连接。
 *
 * <p>Redis 侧由 {@code RedisMessageListenerContainer}（见 RedisConfig）监听
 * {@code gen:events:*} 并回调 {@link #onRedisMessage}；容器自带断线重连，
 * 回调内 try/catch 保证单条消息/单连接失败不影响订阅与其它连接。</p>
 */
@Component
public class ItinerarySseGateway {

    private static final Logger log = LoggerFactory.getLogger(ItinerarySseGateway.class);

    /** 同一行程最多 5 个并发 SSE 连接：防止前端重连风暴或恶意刷新耗尽容器资源。 */
    private static final int MAX_EMITTERS_PER_ITINERARY = 5;

    private final com.fasterxml.jackson.databind.ObjectMapper objectMapper =
            new com.fasterxml.jackson.databind.ObjectMapper();
    /** 注册表：key=itineraryId；增删统一走 {@code ConcurrentHashMap.compute}（同 key 串行化，防孤儿条目）。 */
    private final ConcurrentHashMap<Long, CopyOnWriteArrayList<SseEmitter>> emitters = new ConcurrentHashMap<>();

    /** 建立订阅连接：timeout=0 表示不超时，断连靠 onCompletion/onTimeout/onError 回调清理。 */
    public SseEmitter subscribe(Long itineraryId) {
        SseEmitter emitter = new SseEmitter(0L);
        register(itineraryId, emitter);
        return emitter;
    }

    /** 包内可见：单测可注入 mock emitter 验证广播/清理/超限行为。 */
    void register(Long itineraryId, SseEmitter emitter) {
        // 回调先于入表注册：若连接立即断开也能被清理（对被拒连接 remove 是 no-op）
        emitter.onCompletion(() -> remove(itineraryId, emitter));
        emitter.onTimeout(() -> remove(itineraryId, emitter));
        emitter.onError(t -> remove(itineraryId, emitter));

        final boolean[] rejected = {false};
        emitters.compute(itineraryId, (key, list) -> {
            CopyOnWriteArrayList<SseEmitter> target = list == null ? new CopyOnWriteArrayList<>() : list;
            if (target.size() >= MAX_EMITTERS_PER_ITINERARY) {
                rejected[0] = true;
                return target;
            }
            target.add(emitter);
            return target;
        });
        if (rejected[0]) {
            // 超限：发一条提示后立即 complete（取实现简单者；不抛错，避免被前端误判为网络故障引发重连风暴）
            sendQuietly(itineraryId, emitter, limitEnvelope(itineraryId));
            emitter.complete();
        }
    }

    /** 当前是否有活跃订阅（供故障守卫判断是否需要断开重连）。 */
    public boolean hasSubscribers() {
        return !emitters.isEmpty();
    }

    /**
     * 断开全部连接（Redis 失联守卫调用）：事件源唯一且已失联，保持连接只会让前端
     * 停留在「连接健康但事件永不再来」的假活状态；主动断开后客户端重连失败满 3 次
     * 即自动降级回轮询（协议 §4.3.4 的降级语义）。
     */
    public void closeAll() {
        for (Map.Entry<Long, CopyOnWriteArrayList<SseEmitter>> entry : emitters.entrySet()) {
            for (SseEmitter emitter : entry.getValue()) {
                try {
                    emitter.complete();
                } catch (Exception ignored) {
                    // complete 回调内会自行 remove；重复清理是 no-op
                }
            }
        }
        emitters.clear();
    }

    /** Redis 监听容器回调：channel 形如 gen:events:{itineraryId}，body 为事件信封 JSON 原文。 */
    public void onRedisMessage(String channel, String body) {
        Long itineraryId = parseItineraryId(channel);
        if (itineraryId == null) {
            log.warn("ignore gen event with unexpected channel: {}", channel);
            return;
        }
        broadcast(itineraryId, body);
    }

    /** 把消息原文转发给该行程的所有连接；发送失败的连接移除并 complete（死连接不再占用广播循环）。 */
    void broadcast(Long itineraryId, String json) {
        List<SseEmitter> list = emitters.get(itineraryId);
        if (list == null || list.isEmpty()) {
            return;
        }
        for (SseEmitter emitter : list) {
            sendOrCleanup(itineraryId, emitter, json);
        }
    }

    /**
     * 心跳：15s 一次防止浏览器/代理层空闲断开 SSE。
     * seq 固定 0——心跳不承载业务语义，不占用与 Python 共享的 gen:seq 计数器，
     * 也不必维护独立计数器（实现简单优先）。
     * 心跳调度依赖真实时钟（@Scheduled 单测不触发），广播行为已由 broadcast 测试覆盖，故不单独测试。
     */
    @Scheduled(fixedRate = 15000)
    public void heartbeat() {
        for (Map.Entry<Long, CopyOnWriteArrayList<SseEmitter>> entry : emitters.entrySet()) {
            String json;
            try {
                json = heartbeatEnvelope(entry.getKey());
            } catch (Exception e) {
                log.warn("heartbeat envelope build failed: {}", e.getMessage());
                continue;
            }
            for (SseEmitter emitter : entry.getValue()) {
                sendOrCleanup(entry.getKey(), emitter, json);
            }
        }
    }

    private void sendOrCleanup(Long itineraryId, SseEmitter emitter, String json) {
        try {
            send(emitter, json);
        } catch (Exception e) {
            log.info("sse send failed, remove emitter: itinerary={}, err={}", itineraryId, e.getMessage());
            remove(itineraryId, emitter);
            try {
                emitter.complete();
            } catch (Exception ignored) {
                // complete 触发的回调可能已清理，忽略二次异常
            }
        }
    }

    /** 超限提示也不应让网关挂掉：静默尽力发送。 */
    private void sendQuietly(Long itineraryId, SseEmitter emitter, String json) {
        try {
            send(emitter, json);
        } catch (Exception ignored) {
            // 对方可能已断开，随后的 complete 收尾
        }
    }

    /** 直接写 JSON 字符串（mediaType=application/json），前端 EventSource 按 data: 行解析信封。 */
    private void send(SseEmitter emitter, String json) throws java.io.IOException {
        emitter.send(SseEmitter.event().data(json, MediaType.APPLICATION_JSON));
    }

    /** 移除连接；空表删除 key，防止注册表随行程数无界增长。compute 保证与 register 同 key 串行。 */
    private void remove(Long itineraryId, SseEmitter emitter) {
        emitters.compute(itineraryId, (key, list) -> {
            if (list == null) {
                return null;
            }
            list.remove(emitter);
            return list.isEmpty() ? null : list;
        });
    }

    private static Long parseItineraryId(String channel) {
        if (channel == null || !channel.startsWith(ItineraryEventPublisher.CHANNEL_PREFIX)) {
            return null;
        }
        try {
            return Long.parseLong(channel.substring(ItineraryEventPublisher.CHANNEL_PREFIX.length()));
        } catch (NumberFormatException e) {
            return null;
        }
    }

    /** 心跳信封与业务事件格式一致（seq=0 见 heartbeat 注释）。 */
    private String heartbeatEnvelope(Long itineraryId) throws Exception {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("type", "heartbeat");
        payload.put("itineraryId", itineraryId);
        payload.put("seq", 0);
        payload.put("ts", OffsetDateTime.now().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME));
        payload.put("data", Map.of());
        return objectMapper.writeValueAsString(payload);
    }

    private String limitEnvelope(Long itineraryId) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("code", "TOO_MANY_CONNECTIONS");
        data.put("message", "该行程的实时连接数已达上限，请关闭多余页面后重试");
        data.put("retryable", false);
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("type", "error");
        payload.put("itineraryId", itineraryId);
        payload.put("seq", 0);
        payload.put("ts", OffsetDateTime.now().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME));
        payload.put("data", data);
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (Exception e) {
            return "{}";
        }
    }
}
