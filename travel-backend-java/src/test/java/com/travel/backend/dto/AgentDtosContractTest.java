package com.travel.backend.dto;

import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import jakarta.validation.Validation;
import jakarta.validation.ValidatorFactory;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Agent 强类型 DTO 的 wire 契约测试（纯 Jackson，不起 Spring）。
 *
 * <p>固化两侧契约：</p>
 * <ul>
 *   <li>Python → Java 响应反序列化（含 poi-nearby 的 snake_case 距离键 _distance_m）；</li>
 *   <li>Java → Python 请求序列化为 camelCase（hotelTier/regionHint/radiusM），Python 侧 WireModel 别名可收；</li>
 *   <li>NON_NULL：请求未赋值字段不出现（wire 上"不传即无键"）；</li>
 *   <li>budget 用 Object 字段：BigDecimal 序列化为 JSON 数字（与改造前 Map 透传实体原值一致），空预算为 ""。</li>
 * </ul>
 */
class AgentDtosContractTest {

    private final ObjectMapper mapper = JsonMapper.builder().build();

    @Test
    void butlerNoteResponseShouldDeserializeNote() throws Exception {
        AgentButlerNoteResponse response =
                mapper.readValue("{\"note\":\"你好\"}", AgentButlerNoteResponse.class);
        assertEquals("你好", response.getNote());
    }

    @Test
    void poiIntrosResponseShouldDeserializeIntrosMap() throws Exception {
        AgentPoiIntrosResponse response =
                mapper.readValue("{\"intros\":{\"西湖\":\"介绍\"}}", AgentPoiIntrosResponse.class);
        assertEquals("介绍", response.getIntros().get("西湖"));
    }

    @Test
    void poiNearbyResponseShouldMapSnakeCaseDistanceKey() throws Exception {
        String json = "{\"items\":[{\"name\":\"龙井八景\",\"category\":\"attraction\","
                + "\"rating\":4.5,\"address\":\"杭州\",\"_distance_m\":692}]}";
        AgentPoiNearbyResponse response = mapper.readValue(json, AgentPoiNearbyResponse.class);
        AgentPoiNearbyItem item = response.getItems().get(0);
        assertEquals("龙井八景", item.getName());
        assertEquals("attraction", item.getCategory());
        assertEquals(4.5, item.getRating());
        assertEquals("杭州", item.getAddress());
        assertEquals(692, item.getDistanceM());
    }

    @Test
    void cityGuideResponseShouldDeserializeKindCityMessageSuggestions() throws Exception {
        String json = "{\"kind\":\"city\",\"city\":\"杭州\",\"message\":\"杭州不错\","
                + "\"suggestions\":[{\"name\":\"绍兴\",\"reason\":\"高铁半小时\"}]}";
        AgentCityGuideResponse response = mapper.readValue(json, AgentCityGuideResponse.class);
        assertEquals("city", response.getKind());
        assertEquals("杭州", response.getCity());
        assertEquals("杭州不错", response.getMessage());
        assertEquals(1, response.getSuggestions().size());
        assertEquals("绍兴", response.getSuggestions().get(0).getName());
        assertEquals("高铁半小时", response.getSuggestions().get(0).getReason());
    }

    @Test
    void clarifyResponseShouldAlignWithPythonClarifyResponse() throws Exception {
        String json = "{\"slots\":{\"city\":\"杭州\"},\"missing\":[\"days\"],"
                + "\"question\":\"住几晚？\",\"ready\":false}";
        AgentClarifyResponse response = mapper.readValue(json, AgentClarifyResponse.class);
        assertEquals("杭州", response.getSlots().get("city"));
        assertEquals(List.of("days"), response.getMissing());
        assertEquals("住几晚？", response.getQuestion());
        assertEquals(false, response.getReady());
    }

    @Test
    void clarifyResponseShouldTolerateAbsentFields() throws Exception {
        AgentClarifyResponse response = mapper.readValue("{}", AgentClarifyResponse.class);
        assertNull(response.getSlots());
        assertNull(response.getMissing());
        assertNull(response.getQuestion());
        assertNull(response.getReady());
    }

    @Test
    void butlerNoteRequestShouldSerializeCamelCaseWireKeys() throws Exception {
        AgentButlerNoteRequest request = new AgentButlerNoteRequest();
        request.setCity("杭州");
        request.setDays(3);
        request.setPersons(2);
        request.setPreferences("");
        request.setHotelTier("舒适型");
        request.setRegionHint("浙江");
        request.setBudget(new BigDecimal("50000"));
        request.setRequirements("");
        request.setPlans(List.of(Map.of("day_no", 1, "items", List.of("西湖"))));
        JsonNode wire = mapper.readTree(mapper.writeValueAsString(request));
        assertTrue(wire.has("hotelTier"), "wire 键应为 camelCase hotelTier");
        assertTrue(wire.has("regionHint"), "wire 键应为 camelCase regionHint");
        // budget 为实体原值 BigDecimal 时必须是 JSON 数字（Python f-string 对 50000 与 "50000" 渲染不同）
        assertTrue(wire.get("budget").isNumber(), "budget 应序列化为 JSON 数字");
        assertEquals(50000, wire.get("budget").asInt());
        assertTrue(wire.get("plans").get(0).has("day_no"), "plans 元素沿用 Python 契约的 snake_case 键");
    }

    @Test
    void butlerNoteRequestShouldKeepEmptyStringBudgetForNullEntityBudget() throws Exception {
        AgentButlerNoteRequest request = new AgentButlerNoteRequest();
        request.setCity("杭州");
        // 与改造前 Map.of("budget", "") 兜底一致：实体 budget 为空时 wire 上是空字符串
        request.setBudget("");
        JsonNode wire = mapper.readTree(mapper.writeValueAsString(request));
        assertTrue(wire.get("budget").isTextual());
        assertEquals("", wire.get("budget").asText());
    }

    @Test
    void butlerNoteRequestShouldOmitNullFields() throws Exception {
        AgentButlerNoteRequest request = new AgentButlerNoteRequest();
        request.setCity("杭州");
        JsonNode wire = mapper.readTree(mapper.writeValueAsString(request));
        assertEquals(1, wire.size());
        assertTrue(wire.has("city"));
    }

    @Test
    void poiNearbyRequestShouldSerializeCamelCaseRadiusKeyAndOmitNulls() throws Exception {
        AgentPoiNearbyRequest request = new AgentPoiNearbyRequest();
        request.setCity("杭州");
        request.setName("灵隐寺");
        request.setRadiusM(1000);
        JsonNode wire = mapper.readTree(mapper.writeValueAsString(request));
        assertTrue(wire.has("radiusM"), "wire 键应为 camelCase radiusM");
        assertEquals(1000, wire.get("radiusM").asInt());
        // 未赋值的可选字段（latitude/longitude/limit/category）不出现，与改造前透传语义一致
        assertEquals(3, wire.size());
    }

    @Test
    void clarifyRequestShouldSerializeMessageAndSlots() throws Exception {
        AgentClarifyRequest request = new AgentClarifyRequest();
        request.setMessage("想去杭州玩两天");
        request.setSlots(Map.of());
        JsonNode wire = mapper.readTree(mapper.writeValueAsString(request));
        assertEquals("想去杭州玩两天", wire.get("message").asText());
        assertTrue(wire.get("slots").isObject());
    }

    // ===== M3-③：叙事字段契约（whyThis / tripTheme / dayOptions）=====

    /** Python WireModel 自动 camelCase：DailyPlan 新增 tripTheme/dayOptions、Item 新增 whyThis；
     *  DayOption 的可选回显键 items 必须被 ignoreUnknown 容忍。 */
    @Test
    void dailyPlanShouldDeserializeNarrativeFieldsAndTolerateDayOptionItems() throws Exception {
        String json = "{\"dayNo\":1,"
                + "\"tripTheme\":\"江南水乡慢旅行\","
                + "\"dayOptions\":[{\"label\":\"西湖经典线\",\"summary\":\"断桥—苏堤—雷峰塔\","
                + "\"tradeoff\":\"步行多但打卡全\",\"items\":[\"断桥残雪\"]}],"
                + "\"items\":[{\"itemType\":\"attraction\",\"poiName\":\"西湖\","
                + "\"whyThis\":\"湖光山色是杭州的城市名片\"}]}";
        AgentGenerateResponse.DailyPlan plan = mapper.readValue(json, AgentGenerateResponse.DailyPlan.class);
        assertEquals("江南水乡慢旅行", plan.getTripTheme());
        AgentGenerateResponse.DayOption option = plan.getDayOptions().get(0);
        assertEquals("西湖经典线", option.getLabel());
        assertEquals("断桥—苏堤—雷峰塔", option.getSummary());
        assertEquals("步行多但打卡全", option.getTradeoff());
        assertEquals("湖光山色是杭州的城市名片", plan.getItems().get(0).getWhyThis());
    }

    /** 旧口径响应（无叙事字段）反序列化不受影响：新增字段保持 null，向后兼容。 */
    @Test
    void dailyPlanWithoutNarrativeFieldsShouldKeepNulls() throws Exception {
        AgentGenerateResponse.DailyPlan plan =
                mapper.readValue("{\"dayNo\":2,\"items\":[{\"poiName\":\"灵隐寺\"}]}", AgentGenerateResponse.DailyPlan.class);
        assertNull(plan.getTripTheme());
        assertNull(plan.getDayOptions());
        assertNull(plan.getItems().get(0).getWhyThis());
    }

    /** M3-③：poi-intros 请求透传 intent（与 butlerNote/generate 的 intent 契约一致）。 */
    @Test
    void poiIntrosRequestShouldSerializeIntentKeyAndOmitNulls() throws Exception {
        AgentPoiIntrosRequest request = new AgentPoiIntrosRequest();
        request.setCity("杭州");
        request.setNames(List.of("西湖"));
        request.setIntent("想去杭州看西湖");
        JsonNode wire = mapper.readTree(mapper.writeValueAsString(request));
        assertTrue(wire.has("intent"), "AgentPoiIntrosRequest wire 键应为 camel 同名 intent");
        assertEquals("想去杭州看西湖", wire.get("intent").asText());

        AgentPoiIntrosRequest absent = new AgentPoiIntrosRequest();
        absent.setCity("杭州");
        JsonNode absentWire = mapper.readTree(mapper.writeValueAsString(absent));
        assertTrue(!absentWire.has("intent"), "NON_NULL 策略下未赋值 intent 不应出现");
    }

    // ===== M1：intent 贯通契约 =====

    @Test
    void butlerNoteRequestShouldSerializeIntentKey() throws Exception {
        AgentButlerNoteRequest request = new AgentButlerNoteRequest();
        request.setIntent("想去杭州看西湖");
        JsonNode wire = mapper.readTree(mapper.writeValueAsString(request));
        assertTrue(wire.has("intent"), "AgentButlerNoteRequest wire 键应为 camel 同名 intent");
        assertEquals("想去杭州看西湖", wire.get("intent").asText());
    }

    @Test
    void generateRequestIntentShouldEnforceSize800() {
        try (ValidatorFactory factory = Validation.buildDefaultValidatorFactory()) {
            var validator = factory.getValidator();
            GenerateRequest request = new GenerateRequest();
            request.setCity("杭州");
            request.setDays(3);
            request.setIntent("杭".repeat(801));
            var violations = validator.validate(request);
            assertTrue(violations.stream().anyMatch(v -> "intent".equals(v.getPropertyPath().toString())
                    && "旅行意图最多 800 字".equals(v.getMessage())), "超 800 字应触发 @Size 校验");
            request.setIntent("杭".repeat(800));
            assertTrue(validator.validate(request).isEmpty(), "恰好 800 字应通过校验");
        }
    }
}
