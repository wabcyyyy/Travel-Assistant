package com.travel.backend.config;

import com.travel.backend.entity.ItineraryMain;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.serializer.GenericJacksonJsonRedisSerializer;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNotNull;

/**
 * Redis 缓存值序列化的**往返测试**（无需 Redis 服务）。
 *
 * <p>背景：Boot 4 / Jackson 3 迁移把缓存值序列化器从
 * {@code GenericJackson2JsonRedisSerializer} 换为 {@code GenericJacksonJsonRedisSerializer}
 * （Jackson 3 版），并改为白名单子类型校验器。缓存命中是行程详情读取的热路径，
 * 这里用生产同款 {@link RedisCacheConfig#cacheValueMapper()} + 序列化器验证：
 * 应用实际缓存的形状（实体 / 列表 / 混合 Map，含 java.time 与 BigDecimal）往返后
 * 类型与字段值保持一致——避免升级后缓存读取静默变成「反序列化失败 → 回退 DB」。
 */
class RedisSerializerRoundTripTest {

    private final GenericJacksonJsonRedisSerializer serializer =
            new GenericJacksonJsonRedisSerializer(RedisCacheConfig.cacheValueMapper());

    @SuppressWarnings("unchecked")
    private <T> T roundTrip(T value) {
        byte[] bytes = serializer.serialize(value);
        assertNotNull(bytes, "序列化结果不应为 null");
        Object restored = serializer.deserialize(bytes);
        return (T) restored;
    }

    @Test
    void entityWithTimeAndDecimalFieldsRoundTrips() {
        ItineraryMain main = new ItineraryMain();
        main.setId(42L);
        main.setUserId(7L);
        main.setTitle("杭州两日");
        main.setCity("杭州");
        main.setDays(2);
        main.setPersons(2);
        main.setBudget(new BigDecimal("3000.50"));
        main.setHotelTier("舒适型");
        main.setStayNights(1);
        main.setStatus(2);
        main.setPlanNote("简化交付");
        main.setGenState("COMPLETED");
        main.setGenStartedAt(LocalDateTime.of(2026, 9, 13, 10, 30, 0));
        main.setCreatedAt(LocalDateTime.of(2026, 9, 12, 9, 0, 0));

        ItineraryMain restored = roundTrip(main);

        assertInstanceOf(ItineraryMain.class, restored, "类型信息应随值保存（默认类型序列化生效）");
        assertEquals(main.getId(), restored.getId());
        assertEquals(main.getTitle(), restored.getTitle());
        assertEquals(0, main.getBudget().compareTo(restored.getBudget()));
        assertEquals(main.getGenStartedAt(), restored.getGenStartedAt(), "LocalDateTime 应无损往返");
        assertEquals(main.getCreatedAt(), restored.getCreatedAt());
    }

    @Test
    void listOfNestedMapsRoundTrips() {
        List<Map<String, Object>> dayPlans = new ArrayList<>();
        Map<String, Object> day = new LinkedHashMap<>();
        day.put("dayNo", 1);
        day.put("date", LocalDate.of(2026, 9, 13));
        day.put("items", List.of(Map.of("poiName", "西湖", "cost", new BigDecimal("60.00"))));
        dayPlans.add(day);

        List<?> restored = roundTrip(dayPlans);

        assertInstanceOf(List.class, restored);
        assertEquals(1, restored.size());
        Map<?, ?> restoredDay = (Map<?, ?>) restored.get(0);
        assertEquals(1, restoredDay.get("dayNo"));
        assertEquals(LocalDate.of(2026, 9, 13), restoredDay.get("date"), "LocalDate 应无损往返");
    }

    @Test
    void mixedValueMapKeepsScalarTypes() {
        Map<String, Object> mixed = new LinkedHashMap<>();
        mixed.put("city", "杭州");
        mixed.put("count", 3);
        mixed.put("deep", new BigDecimal("12.34"));
        mixed.put("when", LocalDateTime.of(2026, 1, 1, 0, 0, 0));

        Map<?, ?> restored = roundTrip(mixed);

        assertEquals("杭州", restored.get("city"));
        assertEquals(3, restored.get("count"));
        assertInstanceOf(BigDecimal.class, restored.get("deep"));
        assertInstanceOf(LocalDateTime.class, restored.get("when"));
    }
}
