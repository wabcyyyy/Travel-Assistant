package com.travel.backend;

import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.output.MigrateResult;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;

import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 现有开发库的 Flyway 接入验证（**按需启用，默认不随 CI/常规测试运行**）。
 *
 * <p>运行：{@code mvn -B test -Dtest=FlywayBaselineVerificationTest -Dta.verifyFlyway=true}
 *
 * <p>行为与安全性：对既有库执行 baseline（baseline-version=1）→ 跳过 V1（与现有 schema
 * 等价，已机械核对）→ 无待执行迁移。预期**唯一**变化是新增 {@code flyway_schema_history}
 * 表；本测试会断言业务表数量前后一致，且抽查关键列存在。
 *
 * <p>为何不随常规测试跑：它会改动真实数据库（新增历史表）——不适合在 CI 或本地全量
 * 测试中隐式触发。
 */
@EnabledIfSystemProperty(named = "ta.verifyFlyway", matches = "true")
class FlywayBaselineVerificationTest {

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

    @Test
    void baselineExistingDatabaseAndVerifyNoBusinessDdl() throws Exception {
        Map<String, String> env = dotenv();
        String host = value(env, "MYSQL_HOST", "localhost");
        String port = value(env, "MYSQL_PORT", "3306");
        String db = value(env, "MYSQL_DB", "travel_assistant");
        String user = value(env, "MYSQL_USER", "root");
        String password = value(env, "MYSQL_PASSWORD", "");
        String url = "jdbc:mysql://" + host + ":" + port + "/" + db
                + "?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai&useSSL=false&allowPublicKeyRetrieval=true";

        int businessTablesBefore;
        try (Connection conn = DriverManager.getConnection(url, user, password);
             Statement st = conn.createStatement()) {
            businessTablesBefore = tableCount(st, db, true);
            System.out.println("[verify] 迁移前业务表数: " + businessTablesBefore);
        }

        Flyway flyway = Flyway.configure()
                .dataSource(url, user, password)
                .locations("classpath:db/migration")
                .baselineOnMigrate(true)
                .baselineVersion("1")
                .validateOnMigrate(true)
                .load();
        MigrateResult result = flyway.migrate();
        System.out.printf("[verify] migrate: baselineVersion=%s migrationsExecuted=%d target=%s%n",
                result.initialSchemaVersion, result.migrationsExecuted, result.targetSchemaVersion);

        try (Connection conn = DriverManager.getConnection(url, user, password);
             Statement st = conn.createStatement()) {
            int businessTablesAfter = tableCount(st, db, true);
            assertEquals(businessTablesBefore, businessTablesAfter,
                    "baseline 路径不应改动业务表（仅新增 flyway_schema_history）");

            // 历史表里应有 V1 的 baseline 行（Flyway 历史表用 success 布尔列而非 status）
            try (ResultSet rs = st.executeQuery(
                    "SELECT type, success FROM flyway_schema_history WHERE version = '1'")) {
                assertTrue(rs.next(), "缺少 V1 基线记录");
                assertEquals("BASELINE", rs.getString("type"));
                assertTrue(rs.getBoolean("success"), "基线记录应为成功态");
            }

            // 抽查两端依赖的关键列（V1 应对现有库完全覆盖）
            for (String[] col : new String[][]{
                    {"sys_user", "role"}, {"poi_knowledge", "avg_cost"}, {"poi_knowledge", "ticket_price"},
                    {"itinerary_main", "gen_state"}, {"itinerary_day", "generation_action_id"},
                    {"itinerary_item", "why_note"}, {"itinerary_version", "snapshot_json"}}) {
                try (ResultSet rs = st.executeQuery(
                        "SHOW COLUMNS FROM " + col[0] + " LIKE '" + col[1] + "'")) {
                    assertTrue(rs.next(), col[0] + "." + col[1] + " 缺失");
                }
            }
            assertTrue(tableCount(st, db, false) >= 13, "应包含 flyway_schema_history");
            System.out.println("[verify] OK：baseline 成功、业务表零 DDL、关键列齐备");
        }
        assertNotNull(result);
    }

    private static int tableCount(Statement st, String db, boolean excludeFlyway) throws Exception {
        String sql = "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = '" + db + "'"
                + (excludeFlyway ? " AND table_name <> 'flyway_schema_history'" : "");
        try (ResultSet rs = st.executeQuery(sql)) {
            rs.next();
            return rs.getInt(1);
        }
    }

    /**
     * 空库路径：在**一次性临时库**上执行 V1 全量建表（与 CI schema-migration job 等价的真实验证），
     * 断言 12 张业务表与关键列齐备后删除该临时库（不触碰开发库）。
     */
    @Test
    void v1BuildsFreshDatabaseFromScratch() throws Exception {
        Map<String, String> env = dotenv();
        String host = value(env, "MYSQL_HOST", "localhost");
        String port = value(env, "MYSQL_PORT", "3306");
        String user = value(env, "MYSQL_USER", "root");
        String password = value(env, "MYSQL_PASSWORD", "");
        String adminUrl = "jdbc:mysql://" + host + ":" + port + "/?useSSL=false&allowPublicKeyRetrieval=true";
        String scratch = "ta_v1_migration_check";
        String scratchUrl = "jdbc:mysql://" + host + ":" + port + "/" + scratch
                + "?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai&useSSL=false&allowPublicKeyRetrieval=true";

        try (Connection admin = DriverManager.getConnection(adminUrl, user, password);
             Statement st = admin.createStatement()) {
            st.execute("DROP DATABASE IF EXISTS " + scratch);
            st.execute("CREATE DATABASE " + scratch + " DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci");
        }
        try {
            MigrateResult result = Flyway.configure()
                    .dataSource(scratchUrl, user, password)
                    .locations("classpath:db/migration")
                    .load()
                    .migrate();
            assertEquals(1, result.migrationsExecuted, "空库应执行且仅执行 V1");

            try (Connection conn = DriverManager.getConnection(scratchUrl, user, password);
                 Statement st = conn.createStatement()) {
                int tables = tableCount(st, scratch, false);
                assertEquals(13, tables, "V1 应建 12 张业务表 + flyway_schema_history");
                try (ResultSet rs = st.executeQuery(
                        "SELECT type, success FROM flyway_schema_history WHERE version = '1'")) {
                    assertTrue(rs.next());
                    assertEquals("SQL", rs.getString("type"), "空库路径 V1 应为真实执行（SQL）");
                    assertTrue(rs.getBoolean("success"));
                }
                for (String[] col : new String[][]{
                        {"sys_user", "role"}, {"poi_knowledge", "avg_cost"},
                        {"itinerary_main", "gen_state"}, {"hotel_room_type", "base_price"}}) {
                    try (ResultSet rs = st.executeQuery(
                            "SHOW COLUMNS FROM " + col[0] + " LIKE '" + col[1] + "'")) {
                        assertTrue(rs.next(), col[0] + "." + col[1] + " 缺失");
                    }
                }
                System.out.println("[verify] OK：空库 V1 全量建表成功（12 业务表 + 历史表）");
            }
        } finally {
            try (Connection admin = DriverManager.getConnection(adminUrl, user, password);
                 Statement st = admin.createStatement()) {
                st.execute("DROP DATABASE IF EXISTS " + scratch);
                System.out.println("[verify] 临时库 " + scratch + " 已清理");
            }
        }
    }
}
