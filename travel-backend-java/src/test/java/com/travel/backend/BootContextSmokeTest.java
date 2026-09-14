package com.travel.backend;

import com.travel.backend.common.ItineraryEventChannelManager;
import com.travel.backend.service.impl.ItineraryStatusRecovery;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import tools.jackson.databind.ObjectMapper;

import java.time.LocalDateTime;
import java.util.Date;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Boot 4 / Jackson 3 迁移的运行时冒烟：在 mvn test 阶段真正装配整个应用上下文。
 *
 * <p>完全隔离（不依赖本机环境、不触碰真实数据）：
 * - Flyway 关闭；数据源指向不可达地址（任何误触发的查询都会快速失败而不是打到真实库）；
 * - 启动期会碰 DB/Redis 的两个 ApplicationReadyEvent 监听器以替身替换（mock 方法为空）。
 *
 * <p>验证目标：
 * - 全量 Bean 装配成立（SecurityFilterChain / MyBatis-Plus / CacheManager /
 *   构造注入 ObjectMapper 的各 Service 都能拿到 Boot 提供的 mapper）；
 * - Jackson 线上格式未因 3.x 迁移漂移（java.time=ISO-8601；date-format 对
 *   java.util.Date 仍生效）——这是前后端契约的关键面。
 */
@SpringBootTest(properties = {
        "spring.flyway.enabled=false",
        "spring.datasource.url=jdbc:mysql://127.0.0.1:1/ta_smoke?connectTimeout=200&socketTimeout=200",
        // 应用自带的启动护栏（SecurityStartupValidator）要求 JWT_SECRET ≥32 位，
        // 测试注入一次性占位值（非真实密钥）
        "app.jwt.secret=ci-example-jwt-secret-at-least-32-chars"
})
class BootContextSmokeTest {

    @MockitoBean
    private ItineraryStatusRecovery statusRecovery;

    @MockitoBean
    private ItineraryEventChannelManager eventChannelManager;

    @Autowired
    private ObjectMapper objectMapper;

    @Test
    void contextLoadsAndJacksonWireFormatUnchanged() throws Exception {
        // Boot 必须提供可直接注入的 ObjectMapper（Jackson 3 下为 JsonMapper 子类）
        assertNotNull(objectMapper, "上下文中缺少可注入的 ObjectMapper");

        // java.time 线上格式：ISO-8601（Jackson 2/3 一致，前端按此解析）
        String json = objectMapper.writeValueAsString(
                Map.of("at", LocalDateTime.of(2026, 9, 13, 10, 30, 0)));
        assertTrue(json.contains("2026-09-13T10:30:00"), "LocalDateTime 应为 ISO 格式: " + json);

        // spring.jackson.date-format 仍生效（java.util.Date → yyyy-MM-dd HH:mm:ss）
        String dateJson = objectMapper.writeValueAsString(Map.of("d", new Date(0L)));
        assertTrue(dateJson.matches(".*\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}.*"),
                "java.util.Date 应遵循 spring.jackson.date-format: " + dateJson);
    }
}
