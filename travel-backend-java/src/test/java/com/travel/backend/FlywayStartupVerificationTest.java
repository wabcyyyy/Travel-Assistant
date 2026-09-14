package com.travel.backend;

import com.travel.backend.common.ItineraryEventChannelManager;
import com.travel.backend.service.impl.ItineraryStatusRecovery;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 「空库启动即全 schema」的**应用自身启动路径**验证（**按需启用**）：
 * 用 Boot 的 Flyway 自动配置 + application.yml 的 spring.flyway.* 属性，对一个
 * 一次性临时库启动整个上下文；断言 V1 被真实执行、表结构齐备，结束后删除临时库。
 *
 * <p>运行：{@code mvn -B test -Dtest=FlywayStartupVerificationTest -Dta.verifyFlyway=true}
 *
 * <p>与 {@link FlywayBaselineVerificationTest} 的区别：那个用 Flyway API 直连验证迁移本身；
 * 本类验证 **Boot 4 自动配置与属性绑定**这一段（如 spring.flyway.baseline-on-migrate 生效、
 * 自动配置模块在 classpath、启动期完成迁移），且始终指向临时库、不触碰开发库。
 */
@SpringBootTest(properties = {
        "app.jwt.secret=ci-example-jwt-secret-at-least-32-chars"
})
@org.junit.jupiter.api.condition.EnabledIfSystemProperty(named = "ta.verifyFlyway", matches = "true")
class FlywayStartupVerificationTest {

    private static final String SCRATCH_DB = "ta_flyway_startup_check";
    private static String adminUrl;
    private static String scratchUrl;
    private static String user;
    private static String password;

    /**
     * 上下文的数据源指向临时库：Flyway 自动配置在启动期完成 V1 建表。
     * 临时库在**此处**创建——只有真正加载本测试上下文时才会执行（默认 skip 时不触碰任何库）。
     */
    @DynamicPropertySource
    static void datasource(DynamicPropertyRegistry registry) throws Exception {
        Map<String, String> env = dotenv();
        String host = value(env, "MYSQL_HOST", "localhost");
        String port = value(env, "MYSQL_PORT", "3306");
        user = value(env, "MYSQL_USER", "root");
        password = value(env, "MYSQL_PASSWORD", "");
        adminUrl = "jdbc:mysql://" + host + ":" + port + "/?useSSL=false&allowPublicKeyRetrieval=true";
        scratchUrl = "jdbc:mysql://" + host + ":" + port + "/" + SCRATCH_DB
                + "?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai&useSSL=false&allowPublicKeyRetrieval=true";
        try (Connection admin = DriverManager.getConnection(adminUrl, user, password);
             Statement st = admin.createStatement()) {
            st.execute("DROP DATABASE IF EXISTS " + SCRATCH_DB);
            st.execute("CREATE DATABASE " + SCRATCH_DB + " DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci");
        }
        registry.add("spring.datasource.url", () -> scratchUrl);
    }

    @MockitoBean
    private ItineraryStatusRecovery statusRecovery;

    @MockitoBean
    private ItineraryEventChannelManager eventChannelManager;

    @Autowired
    private org.springframework.core.env.Environment environment;

    @Test
    void contextStartsAndFlywayMigratesFreshSchema() throws Exception {
        // 启动期完成迁移：空库执行 V1（boot 的 Flyway 自动配置 + spring.flyway.* 属性生效）
        assertEquals("true", environment.getProperty("spring.flyway.baseline-on-migrate"),
                "application.yml 的 baseline-on-migrate 应被加载");
        try (Connection conn = DriverManager.getConnection(scratchUrl, user, password);
             Statement st = conn.createStatement()) {
            try (ResultSet rs = st.executeQuery(
                    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='" + SCRATCH_DB + "'")) {
                rs.next();
                assertEquals(13, rs.getInt(1), "启动期应建 12 张业务表 + flyway_schema_history");
            }
            try (ResultSet rs = st.executeQuery(
                    "SELECT type, success FROM flyway_schema_history WHERE version = '1'")) {
                assertTrue(rs.next(), "缺少 V1 记录");
                assertEquals("SQL", rs.getString("type"), "空库启动应由 Flyway 真实执行 V1");
                assertTrue(rs.getBoolean("success"));
            }
        }
        System.out.println("[verify] OK：应用启动路径在空库完成 V1 全量建表");
    }

    @AfterAll
    static void dropScratch() throws Exception {
        try (Connection admin = DriverManager.getConnection(adminUrl, user, password);
             Statement st = admin.createStatement()) {
            st.execute("DROP DATABASE IF EXISTS " + SCRATCH_DB);
            System.out.println("[verify] 临时库 " + SCRATCH_DB + " 已清理");
        }
    }

    private static Map<String, String> dotenv() throws Exception {
        Map<String, String> env = new HashMap<>();
        Path dotenv = Path.of(".env");
        if (Files.exists(dotenv)) {
            for (String line : Files.readAllLines(dotenv)) {
                String trimmed = line.trim();
                if (trimmed.isEmpty() || trimmed.startsWith("#") || !trimmed.contains("=")) {
                    continue;
                }
                int idx = trimmed.indexOf('=');
                env.putIfAbsent(trimmed.substring(0, idx).trim(), trimmed.substring(idx + 1).trim());
            }
        }
        return env;
    }

    private static String value(Map<String, String> env, String key, String fallback) {
        String fromProcess = System.getenv(key);
        if (fromProcess != null && !fromProcess.isBlank()) {
            return fromProcess;
        }
        return env.getOrDefault(key, fallback);
    }
}
