package com.travel.backend.common;

import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;
import com.travel.backend.dto.AgentGenerateResponse;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;

import java.io.InputStream;
import java.lang.reflect.Field;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 跨语言流事件契约的 Java 消费方测试。
 *
 * <p>样例来自 Python 侧模型真实 dump（generate-day / generate-stream 的 wire 形状）：
 * - 每个样例必须通过契约校验，且能反序列化进 AgentGenerateResponse DTO；
 * - 「改名实验」：字段改名必须被拒绝（而不是 convertValue 后静默落 null）；
 * - DTO 反射覆盖：Java 读取的每个字段都必须在 schema 中有定义。
 */
class AgentStreamContractTest {

    private static final ObjectMapper JSON = JsonMapper.builder().build();

    private static JsonNode fixture(String name) throws Exception {
        try (InputStream in = new ClassPathResource("contracts/" + name + ".json").getInputStream()) {
            return JSON.readTree(in);
        }
    }

    private static JsonNode schema() throws Exception {
        try (InputStream in = new ClassPathResource("contracts/stream_events.schema.json").getInputStream()) {
            return JSON.readTree(in);
        }
    }

    private static boolean mentions(List<String> violations, String needle) {
        return violations.stream().anyMatch(v -> v.contains(needle));
    }

    @Test
    void everyFixtureSatisfiesContract() throws Exception {
        AgentStreamContract contract = AgentStreamContract.get();
        for (String name : List.of("start", "day", "day_patch", "suggestions", "done", "error")) {
            JsonNode event = fixture(name);
            assertTrue(contract.isKnownType(event), name + " 应为契约内已知类型");
            List<String> violations = contract.violations(event);
            assertTrue(violations.isEmpty(),
                    name + " 样例应通过契约校验，实际违规: " + AgentStreamContract.summarize(violations));
        }
    }

    @Test
    void dayFixtureDeserializesIntoJavaDto() throws Exception {
        JsonNode planNode = fixture("day").get("plan");
        AgentGenerateResponse.DailyPlan plan =
                JSON.treeToValue(planNode, AgentGenerateResponse.DailyPlan.class);
        assertEquals(1, plan.getDayNo().intValue());
        assertEquals("巴塞罗那·高迪之光", plan.getTripTheme());
        assertEquals(3, plan.getItems().size());
        AgentGenerateResponse.Item first = plan.getItems().get(0);
        assertEquals("attraction", first.getItemType());
        assertTrue(first.getPoiName().startsWith("圣家堂"));
        assertEquals(0, new BigDecimal("26").compareTo(first.getCost()));
        assertEquals(0, new BigDecimal("41.4036").compareTo(first.getLatitude()));
        // 备选池事件同样可落库
        List<AgentGenerateResponse.Suggestion> rows = JSON.convertValue(
                fixture("suggestions").get("items"),
                new tools.jackson.core.type.TypeReference<List<AgentGenerateResponse.Suggestion>>() { });
        assertEquals("米拉之家", rows.get(0).getName());
        assertTrue(rows.get(0).getNeedReservation());
    }

    /** 改名实验（核心验收）：必填字段与可选字段改名都必须被契约拒绝，而非静默丢字段。 */
    @Test
    void renamedFieldsAreRejectedNotSilentlyDropped() throws Exception {
        AgentStreamContract contract = AgentStreamContract.get();

        // 基线：原样样例通过
        JsonNode baseline = fixture("day");
        assertTrue(contract.violations(baseline).isEmpty());

        // 必填字段改名：dayNo → day_no（旧实现下 asInt(0) 静默落 0，事件被丢弃）
        ObjectNode requiredRenamed = (ObjectNode) baseline.deepCopy();
        ObjectNode plan1 = (ObjectNode) requiredRenamed.get("plan");
        plan1.set("day_no", plan1.remove("dayNo"));
        List<String> requiredViolations = contract.violations(requiredRenamed);
        assertFalse(requiredViolations.isEmpty(), "必填字段改名必须产生契约违规");
        assertTrue(mentions(requiredViolations, "dayNo"), "违规信息应指向缺失的 dayNo");

        // 可选字段改名：note → remarks（旧实现下静默落 null，用户看不到当天说明）
        ObjectNode optionalRenamed = (ObjectNode) baseline.deepCopy();
        ObjectNode plan2 = (ObjectNode) optionalRenamed.get("plan");
        plan2.set("remarks", plan2.remove("note"));
        List<String> optionalViolations = contract.violations(optionalRenamed);
        assertFalse(optionalViolations.isEmpty(), "可选字段改名同样必须违规（wire 全键必填）");
        assertTrue(mentions(optionalViolations, "note"), "违规信息应指向缺失的 note");
    }

    @Test
    void missingRequiredFieldIsRejected() throws Exception {
        ObjectNode done = (ObjectNode) fixture("done");
        done.remove("daysEmitted");
        List<String> violations = AgentStreamContract.get().violations(done);
        assertFalse(violations.isEmpty());
        assertTrue(mentions(violations, "daysEmitted"));
    }

    @Test
    void unknownEventTypeIsForwardCompatible() throws Exception {
        JsonNode progress = JSON.readTree("{\"type\":\"progress\",\"step\":1}");
        assertFalse(AgentStreamContract.get().isKnownType(progress),
                "未知类型应被视为前向兼容的附加事件，由编排层忽略而非判违规");
    }

    /** 消费方期望：DTO 读取的每个字段都必须在 schema 中有定义（防 Java 侧单边加字段/契约漏字段）。 */
    @Test
    void schemaCoversEveryFieldJavaConsumes() throws Exception {
        JsonNode defs = schema().path("$defs");
        assertDtoCovered(defs, "DailyPlan", AgentGenerateResponse.DailyPlan.class);
        assertDtoCovered(defs, "TripItem", AgentGenerateResponse.Item.class);
        assertDtoCovered(defs, "Suggestion", AgentGenerateResponse.Suggestion.class);
        assertDtoCovered(defs, "DayOption", AgentGenerateResponse.DayOption.class);
    }

    /** 事件级必填字段钉死：Python 侧降级为可选/改名即在此暴露。 */
    @Test
    void eventLevelRequiredFieldsPinned() throws Exception {
        JsonNode defs = schema().path("$defs");
        for (String name : List.of("StartEvent", "DayEvent", "DayPatchEvent",
                "SuggestionsEvent", "DoneEvent", "ErrorEvent")) {
            JsonNode required = defs.path(name).path("required");
            assertTrue(required.isArray() && !required.isEmpty(), name + " 应有必填字段");
            assertEquals("type", required.get(0).asText(), name + " 的 type 必须必填");
        }
        List<String> doneRequired = new ArrayList<>();
        defs.path("DoneEvent").path("required").forEach(n -> doneRequired.add(n.asText()));
        assertTrue(doneRequired.containsAll(List.of(
                "daysExpected", "daysEmitted", "tripTheme", "complete", "message")));
    }

    private static void assertDtoCovered(JsonNode defs, String schemaName, Class<?> dtoClass) {
        JsonNode properties = defs.path(schemaName).path("properties");
        assertTrue(properties.isObject(), "schema 缺少 " + schemaName + " 定义");
        for (Field field : dtoClass.getDeclaredFields()) {
            if (field.isSynthetic()) {
                continue;
            }
            assertTrue(properties.has(field.getName()),
                    dtoClass.getSimpleName() + "." + field.getName()
                            + " 未在契约 " + schemaName + " 中定义");
        }
    }
}
