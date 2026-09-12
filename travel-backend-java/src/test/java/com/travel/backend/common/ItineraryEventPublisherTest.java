package com.travel.backend.common;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 事件发布器单测（不依赖真实 Redis）：
 * 验证 channel 选择、信封键（type/itineraryId/seq/ts/data，camelCase）、seq 递增、
 * Redis 异常不向上传播，以及 chat 流本地直发变体 publishLocal。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class ItineraryEventPublisherTest {

    @Mock
    private StringRedisTemplate redis;
    @Mock
    private ValueOperations<String, String> valueOps;

    private ItineraryEventPublisher publisher;
    private final ObjectMapper json = new ObjectMapper();

    @BeforeEach
    void setUp() {
        when(redis.opsForValue()).thenReturn(valueOps);
        when(valueOps.increment(anyString())).thenReturn(1L);
        when(redis.expire(anyString(), any(Duration.class))).thenReturn(true);
        publisher = new ItineraryEventPublisher(redis);
    }

    /** 发布走 gen:events:{id} 频道，信封含协议五键且 seq 取自 INCR，计数器刷新 7200s 过期。 */
    @Test
    void publishSendsEnvelopeToPerItineraryChannel() throws Exception {
        when(valueOps.increment("gen:seq:9")).thenReturn(3L);

        publisher.publish(9L, "day_start", Map.of("dayNo", 1));

        ArgumentCaptor<String> body = ArgumentCaptor.forClass(String.class);
        verify(redis).convertAndSend(eq("gen:events:9"), body.capture());
        JsonNode envelope = json.readTree(body.getValue());
        assertEquals("day_start", envelope.get("type").asText());
        assertEquals(9L, envelope.get("itineraryId").asLong());
        assertEquals(3L, envelope.get("seq").asLong());
        // ts 必须是带时区的 ISO-8601（与 Python 端协议一致）
        assertTrue(OffsetDateTime.parse(envelope.get("ts").asText()).getOffset()
                .equals(OffsetDateTime.now().getOffset()));
        assertEquals(1, envelope.get("data").get("dayNo").asInt());
        // seq 计数器与 Python 共用：INCR 后刷新 EXPIRE 7200s
        verify(redis).expire(eq("gen:seq:9"), eq(Duration.ofSeconds(7200)));
    }

    /** 同一行程连续发布时 seq 严格递增（INCR 原子取号）。 */
    @Test
    void seqIncrementsAcrossPublishes() throws Exception {
        when(valueOps.increment("gen:seq:5")).thenReturn(1L, 2L, 3L);

        publisher.publish(5L, "day_start", Map.of("dayNo", 1));
        publisher.publish(5L, "day_done", Map.of("dayNo", 1));
        publisher.publish(5L, "complete", Map.of("status", "COMPLETED"));

        ArgumentCaptor<String> body = ArgumentCaptor.forClass(String.class);
        verify(redis, org.mockito.Mockito.times(3)).convertAndSend(eq("gen:events:5"), body.capture());
        List<Long> seqs = new ArrayList<>();
        for (String value : body.getAllValues()) {
            seqs.add(json.readTree(value).path("seq").asLong());
        }
        assertEquals(List.of(1L, 2L, 3L), seqs);
    }

    /** Redis 取号失败也不向上传播：退化为本地 seq 继续组信封（INCR 异常 → convertAndSend 仍可能尝试）。 */
    @Test
    void redisIncrFailureDoesNotPropagate() {
        when(valueOps.increment(anyString())).thenThrow(new RuntimeException("redis down"));
        doThrow(new RuntimeException("redis down")).when(redis).convertAndSend(anyString(), anyString());

        assertDoesNotThrow(() -> publisher.publish(1L, "day_start", Map.of("dayNo", 1)));
        assertDoesNotThrow(() -> publisher.error(1L, "AGENT_ERROR", "boom", true));
    }

    /** convertAndSend 失败只记 warn：事件是尽力而为通知，DB 是真相。 */
    @Test
    void convertAndSendFailureDoesNotPropagate() {
        doThrow(new RuntimeException("redis down")).when(redis).convertAndSend(anyString(), anyString());

        assertDoesNotThrow(() -> publisher.dayStart(2L, 1));
    }

    /** error 便捷方法 data 键为 camelCase：code/message/retryable。 */
    @Test
    void errorEventCarriesCamelCasePayload() throws Exception {
        publisher.error(3L, "AGENT_ERROR", "生成失败", true);

        ArgumentCaptor<String> body = ArgumentCaptor.forClass(String.class);
        verify(redis).convertAndSend(eq("gen:events:3"), body.capture());
        JsonNode data = json.readTree(body.getValue()).get("data");
        assertEquals("AGENT_ERROR", data.get("code").asText());
        assertEquals("生成失败", data.get("message").asText());
        assertTrue(data.get("retryable").asBoolean());
    }

    /** day_done 的 data 含 dayNo/theme/itemCount/note（note 允许 null 而不抛 NPE）。 */
    @Test
    void dayDoneCarriesCamelCaseKeysWithNullNote() throws Exception {
        publisher.dayDone(4L, 2, "古镇漫步", 5, null);

        ArgumentCaptor<String> body = ArgumentCaptor.forClass(String.class);
        verify(redis).convertAndSend(eq("gen:events:4"), body.capture());
        JsonNode data = json.readTree(body.getValue()).get("data");
        assertEquals(2, data.get("dayNo").asInt());
        assertEquals("古镇漫步", data.get("theme").asText());
        assertEquals(5, data.get("itemCount").asInt());
        assertTrue(data.get("note").isNull());
    }

    /** complete 事件携带 status/dayCount/degradedDays/versionId。 */
    @Test
    void completeCarriesDegradedDaysAndVersionId() throws Exception {
        publisher.complete(6L, "PARTIAL", 3, List.of(2, 3), 88L);

        ArgumentCaptor<String> body = ArgumentCaptor.forClass(String.class);
        verify(redis).convertAndSend(eq("gen:events:6"), body.capture());
        JsonNode data = json.readTree(body.getValue()).get("data");
        assertEquals("PARTIAL", data.get("status").asText());
        assertEquals(3, data.get("dayCount").asInt());
        assertEquals(List.of(2, 3), json.convertValue(data.get("degradedDays"),
                json.getTypeFactory().constructCollectionType(List.class, Integer.class)));
        assertEquals(88L, data.get("versionId").asLong());
    }

    /** publishLocal 不走 Redis，信封经 sink 回调送达（chat 流点对点场景）。 */
    @Test
    void publishLocalDeliversEnvelopeToSinkWithoutRedis() throws Exception {
        when(valueOps.increment("gen:seq:5")).thenReturn(7L);
        List<String> received = new ArrayList<>();

        publisher.publishLocal(5L, "chat_token", Map.of("messageId", "ab12cd34", "delta", "你好"), received::add);

        assertEquals(1, received.size());
        JsonNode envelope = json.readTree(received.get(0));
        assertEquals("chat_token", envelope.get("type").asText());
        assertEquals(7L, envelope.get("seq").asLong());
        assertEquals("你好", envelope.get("data").get("delta").asText());
        verify(redis, never()).convertAndSend(anyString(), anyString());
    }

    /** publishLocal 的信封与 publish 共用同一取号逻辑：seq 连续（本地流与全局流一致）。 */
    @Test
    void publishLocalSharesSeqCounterWithPublish() throws Exception {
        when(valueOps.increment("gen:seq:8")).thenReturn(10L, 11L);
        List<String> received = new ArrayList<>();

        publisher.publish(8L, "day_start", Map.of("dayNo", 1));
        publisher.publishLocal(8L, "chat_done", Map.of("messageId", "x"), received::add);

        assertEquals(11L, json.readTree(received.get(0)).get("seq").asLong());
    }

    /** 非本人/异常路径不影响：null data 时 data 输出为空对象而非 "null"。 */
    @Test
    void nullDataSerializesAsEmptyObject() throws Exception {
        publisher.publish(7L, "heartbeat", null);

        ArgumentCaptor<String> body = ArgumentCaptor.forClass(String.class);
        verify(redis).convertAndSend(eq("gen:events:7"), body.capture());
        JsonNode envelope = json.readTree(body.getValue());
        assertTrue(envelope.get("data").isObject());
        assertFalse(envelope.get("data").isNull());
    }
}
