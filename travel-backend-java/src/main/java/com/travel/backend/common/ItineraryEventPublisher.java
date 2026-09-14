package com.travel.backend.common;

import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Consumer;

/**
 * 生成进度事件发布器（M2-③ AD2 SSE 的 Java 环节）。
 *
 * <p>与 Python 端共用同一事件协议：信封 {@code {"type","itineraryId","seq","ts","data"}}，
 * 发布到 Redis pub/sub channel {@code gen:events:{itineraryId}}；seq 取自
 * {@code INCR gen:seq:{itineraryId}}（与 Python 在同一计数器上取号，EXPIRE 7200s）。
 * SSE 网关订阅 {@code gen:events:*} 后把消息原文转发给浏览器。</p>
 *
 * <p>事件是尽力而为通知，数据库才是真相：任何 Redis 异常只记 warn 不向上抛，
 * 保证事件通道故障不影响生成主流程（前端仍可用详情轮询兜底）。
 * StringRedisTemplate 本身线程安全，逐日生成/富化/导出多线程并发发布无需加锁。</p>
 */
@Component
public class ItineraryEventPublisher {

    private static final Logger log = LoggerFactory.getLogger(ItineraryEventPublisher.class);

    public static final String CHANNEL_PREFIX = "gen:events:";
    private static final String SEQ_KEY_PREFIX = "gen:seq:";
    /** 与 Python 端约定一致：seq 计数器 7200s 过期，覆盖一次完整生成的时长。 */
    private static final Duration SEQ_TTL = Duration.ofSeconds(7200);

    private final StringRedisTemplate redis;
    /** 事件 JSON 用独立 ObjectMapper：不受 Spring 全局/Redis 序列化配置影响，保证与 Python 端信封格式一致。 */
    private final ObjectMapper objectMapper = JsonMapper.builder().build();
    /** Redis 不可用时 chat 流等本地事件的 seq 兜底：进程内自增即可满足单调递增。 */
    private final AtomicLong fallbackSeq = new AtomicLong();

    public ItineraryEventPublisher(StringRedisTemplate redis) {
        this.redis = redis;
    }

    /** 发布事件到 Redis pub/sub；失败仅记 warn，绝不向生成主流程传播。 */
    public void publish(Long itineraryId, String type, Map<String, Object> data) {
        try {
            String json = envelope(itineraryId, type, data);
            redis.convertAndSend(CHANNEL_PREFIX + itineraryId, json);
        } catch (Exception e) {
            log.warn("publish gen event failed: itinerary={}, type={}, err={}",
                    itineraryId, type, e.getMessage());
        }
    }

    /**
     * 本地直发变体：取 seq 组信封后不经 Redis，直接回调 sink 发送（chat SSE 流用）。
     * 让 chat_token/chat_draft/chat_done 与全局事件共用同一 seq 计数器和信封格式，
     * 但 chat 是点对点会话，走 Redis 广播会串台到其它订阅者，故本地直发。
     * sink（emitter）异常向上传播：调用方需要据此停止发送并清理连接。
     */
    public void publishLocal(Long itineraryId, String type, Map<String, Object> data, Consumer<String> sink) {
        sink.accept(envelope(itineraryId, type, data));
    }

    // ================= 便捷方法（data 键统一 camelCase） =================

    /** 单日开始生成。 */
    public void dayStart(Long itineraryId, int dayNo) {
        publish(itineraryId, "day_start", Map.of("dayNo", dayNo));
    }

    /** 单日落库成功，回执数据取自 DailyPlan（note 可为 null，用 LinkedHashMap 容忍空值）。 */
    public void dayDone(Long itineraryId, int dayNo, String theme, int itemCount, String note) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("dayNo", dayNo);
        data.put("theme", theme);
        data.put("itemCount", itemCount);
        data.put("note", note);
        publish(itineraryId, "day_done", data);
    }

    /** 降级通知：scope 标识降级范围（day_{n}/butler/poi_intros/research），fallback 为前端可展示的兜底文案。 */
    public void degraded(Long itineraryId, String scope, String reason, String fallback) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("scope", scope);
        data.put("reason", reason);
        data.put("fallback", fallback);
        publish(itineraryId, "degraded", data);
    }

    /** 整体失败通知（retryable=true 表示前端可提示重试）。 */
    public void error(Long itineraryId, String code, String message, boolean retryable) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("code", code);
        data.put("message", message);
        data.put("retryable", retryable);
        publish(itineraryId, "error", data);
    }

    /**
     * 生成收尾终态事件：前端据此停止监听。
     * versionId 为版本快照 id（createSnapshot 无返回值/失败时为 null）；degradedDays 为未 SUCCEEDED 的 dayNo。
     */
    public void complete(Long itineraryId, String status, Integer dayCount,
                         List<Integer> degradedDays, Long versionId) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("status", status);
        data.put("dayCount", dayCount);
        data.put("degradedDays", degradedDays == null ? List.of() : degradedDays);
        data.put("versionId", versionId);
        publish(itineraryId, "complete", data);
    }

    /** AI 管家讲解写回成功（preview 截断 60 字由调用方处理，事件体不携带长文本）。 */
    public void butlerNote(Long itineraryId, int length, String preview) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("length", length);
        data.put("preview", preview);
        publish(itineraryId, "butler_note", data);
    }

    /** PDF 导出任务完成，downloadUrl 与 /api/export 任务查询响应一致。 */
    public void exportDone(Long itineraryId, Long taskId, String status, String downloadUrl) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("taskId", taskId);
        data.put("status", status);
        data.put("downloadUrl", downloadUrl);
        publish(itineraryId, "export_done", data);
    }

    /** chat 流 token 分片（通常经 publishLocal 本地直发，此便捷方法供非流式场景复用信封）。 */
    public void chatToken(Long itineraryId, String messageId, String delta) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("messageId", messageId);
        data.put("delta", delta);
        publish(itineraryId, "chat_token", data);
    }

    /** chat 流草稿方案（plans/baseRevision 与 /chat-edit 响应字段一致）。 */
    public void chatDraft(Long itineraryId, String messageId, Object plans, String baseRevision) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("messageId", messageId);
        data.put("plans", plans);
        data.put("baseRevision", baseRevision);
        publish(itineraryId, "chat_draft", data);
    }

    // ================= 信封组装（组信封+取 seq 收拢于此，publish/publishLocal 复用） =================

    /**
     * 组装协议信封 JSON。包内可见供同包测试校验信封键与 seq 取号。
     * seq 先 INCR 再刷新 EXPIRE 7200s（滑动过期：持续生成期间计数器不会中途清零）。
     */
    String envelope(Long itineraryId, String type, Map<String, Object> data) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("type", type);
        payload.put("itineraryId", itineraryId);
        payload.put("seq", nextSeq(itineraryId));
        // OffsetDateTime.now() 按系统时区输出 ISO-8601 带时区时间串（如 2026-09-11T15:30:00.123+08:00）
        payload.put("ts", OffsetDateTime.now().format(DateTimeFormatter.ISO_OFFSET_DATE_TIME));
        payload.put("data", data == null ? Map.of() : data);
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (Exception e) {
            throw new IllegalStateException("事件信封序列化失败: " + type, e);
        }
    }

    /** 取事件序号：Redis INCR 失败（不可用等）退化为进程内自增，保证本地事件流不中断。 */
    private long nextSeq(Long itineraryId) {
        try {
            String key = SEQ_KEY_PREFIX + itineraryId;
            Long seq = redis.opsForValue().increment(key);
            if (seq == null) {
                throw new IllegalStateException("INCR returned null");
            }
            redis.expire(key, SEQ_TTL);
            return seq;
        } catch (Exception e) {
            log.warn("event seq incr failed for itinerary {}: {}, fallback to local counter",
                    itineraryId, e.getMessage());
            return fallbackSeq.incrementAndGet();
        }
    }
}
