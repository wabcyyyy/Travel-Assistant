package com.travel.backend.service.impl;

import tools.jackson.databind.json.JsonMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import com.travel.backend.common.BizException;
import com.travel.backend.entity.BudgetDetail;
import com.travel.backend.entity.ItineraryChatMessage;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.mapper.ItineraryChatMessageMapper;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.service.AgentService;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 行程对话、草稿版本和待确认动作。
 *
 * 草稿应用服务只依赖这里提供的版本/确认能力，不直接处理对话 JSON 的存储细节。
 */
@Service
public class ItineraryChatService {

    private final ItineraryChatMessageMapper chatMessageMapper;
    private final ItineraryDayMapper dayMapper;
    private final ItineraryItemMapper itemMapper;
    private final AgentService agentService;
    private final ItineraryQueryService queryService;
    private final ObjectMapper objectMapper = JsonMapper.builder().build();

    public ItineraryChatService(ItineraryChatMessageMapper chatMessageMapper,
                                ItineraryDayMapper dayMapper,
                                ItineraryItemMapper itemMapper,
                                AgentService agentService,
                                ItineraryQueryService queryService) {
        this.chatMessageMapper = chatMessageMapper;
        this.dayMapper = dayMapper;
        this.itemMapper = itemMapper;
        this.agentService = agentService;
        this.queryService = queryService;
    }

    /**
     * chatTurn 请求上下文：chatBody 发给 Python；baseRevision 供草稿一致性校验与 chat_draft 事件复用。
     */
    public record ChatTurnContext(Map<String, Object> chatBody, String baseRevision) {}

    /**
     * 构建 chatTurn 请求上下文——阻塞版 chatEdit 与 SSE 流式版（/chat-edit/stream）
     * 的「同参构造」入口，保证两条路径发给 Agent 的输入完全一致。
     */
    public ChatTurnContext buildChatTurnContext(Long userId, Long itineraryId, String message,
                                                List<Map<String, Object>> history) {
        ItineraryMain main = queryService.findOwnedMain(userId, itineraryId);
        List<Map<String, Object>> persistedHistory = chatHistory(userId, itineraryId);
        List<Map<String, Object>> effectiveHistory = persistedHistory.isEmpty()
                ? (history == null ? List.of() : history)
                : persistedHistory.stream()
                .map(item -> Map.<String, Object>of(
                        "role", item.getOrDefault("role", "ai"),
                        "content", item.getOrDefault("content", "")))
                .toList();
        List<Map<String, Object>> persistedPlans = currentPlans(itineraryId);
        String baseRevision = planRevision(persistedPlans);
        List<Map<String, Object>> plans = latestPendingPlans(userId, itineraryId, baseRevision);
        if (plans.isEmpty()) {
            plans = persistedPlans;
        }

        Map<String, Object> chatBody = new HashMap<>();
        chatBody.put("city", main.getCity());
        // 有未应用的“调整行程天数”草稿时，后续对话应继续基于草稿天数，而不是数据库旧值。
        chatBody.put("days", plans.size());
        chatBody.put("persons", main.getPersons() == null ? 1 : main.getPersons());
        chatBody.put("budget", main.getBudget() == null ? null : main.getBudget().doubleValue());
        List<BudgetDetail> currentBudgets = queryService.findBudgetList(itineraryId);
        chatBody.put("current_total", queryService.sumAmount(currentBudgets).doubleValue());
        chatBody.put("current_hotel_total", currentBudgets.stream()
                .filter(b -> "酒店".equals(b.getCategory()))
                .map(BudgetDetail::getAmount).filter(java.util.Objects::nonNull)
                .reduce(BigDecimal.ZERO, BigDecimal::add).doubleValue());
        chatBody.put("start_date", main.getStartDate() == null ? null : main.getStartDate().toString());
        chatBody.put("end_date", main.getEndDate() == null ? null : main.getEndDate().toString());
        chatBody.put("preferences", main.getPreferences() == null ? List.of()
                : List.of(main.getPreferences().split(",")));
        chatBody.put("hotel_tier", main.getHotelTier());
        chatBody.put("plans", plans);
        chatBody.put("history", effectiveHistory.size() <= 20 ? effectiveHistory
                : effectiveHistory.subList(effectiveHistory.size() - 20, effectiveHistory.size()));
        chatBody.put("message", message == null ? "" : message);
        return new ChatTurnContext(chatBody, baseRevision);
    }

    public Map<String, Object> chatEdit(Long userId, Long itineraryId, String message,
                                        List<Map<String, Object>> history) {
        ChatTurnContext ctx = buildChatTurnContext(userId, itineraryId, message, history);
        JsonNode node = agentService.chatTurn(ctx.chatBody());
        return finalizeChatTurn(userId, itineraryId, message, ctx, node);
    }

    /**
     * 把 chatTurn 结果组装为与 /chat-edit 响应一致的出参，并落库对话记忆（用户 + AI 两条）。
     * 抽成公共收尾方法供 SSE 流式变体复用：流式路径必须与非流式路径同样落库，否则
     * 对话历史缺失、酒店提案的 pendingAction 语义（requirePendingAction 依赖落库消息）失效。
     */
    public Map<String, Object> finalizeChatTurn(Long userId, Long itineraryId, String message,
                                                ChatTurnContext ctx, JsonNode node) {
        String baseRevision = ctx.baseRevision();

        Map<String, Object> out = new HashMap<>();
        out.put("reply", node.path("reply").asText("已更新草稿"));
        out.put("changed", node.path("changed").asBoolean(false));
        List<Object> responsePlans = draftPlansFromTurn(node, baseRevision);
        List<Object> responseHotelOptions = attachBaseRevision(
                objectMapperTreeList(node.get("hotelOptions")), baseRevision, true);
        out.put("plans", responsePlans);
        out.put("hotelOptions", responseHotelOptions);
        out.put("baseRevision", baseRevision);
        out.put("requiresConfirmation", node.path("requiresConfirmation").asBoolean(false));
        out.put("planDocument", node.get("planDocument"));
        out.put("operations", objectMapperTreeList(node.get("operations")));
        out.put("pendingAction", node.get("pendingAction"));

        saveChatMessage(userId, itineraryId, "user", message, List.of(), List.of(), false);
        if (Boolean.TRUE.equals(out.get("changed")) || !responseHotelOptions.isEmpty()) {
            invalidatePendingActions(userId, itineraryId);
        }
        ItineraryChatMessage aiMessage = saveChatMessage(userId, itineraryId, "ai", String.valueOf(out.get("reply")),
                (List<?>) out.get("plans"), (List<?>) out.get("hotelOptions"),
                Boolean.TRUE.equals(out.get("changed")));
        out.put("messageId", aiMessage.getId());
        return out;
    }

    /**
     * 从 chatTurn 结果取出与 /chat-edit 响应字段一致的 plans（逐项附 _baseRevision），
     * 供 SSE chat_draft 事件复用，保证流式与非流式响应结构一致。
     */
    public List<Object> draftPlansFromTurn(JsonNode node, String baseRevision) {
        return attachBaseRevision(objectMapperTreeList(node.get("plans")), baseRevision, false);
    }

    public List<Map<String, Object>> chatHistory(Long userId, Long itineraryId) {
        queryService.findOwnedMain(userId, itineraryId);
        List<ItineraryChatMessage> messages = chatMessageMapper.selectList(
                new LambdaQueryWrapper<ItineraryChatMessage>()
                        .eq(ItineraryChatMessage::getItineraryId, itineraryId)
                        .eq(ItineraryChatMessage::getUserId, userId)
                        .orderByDesc(ItineraryChatMessage::getId)
                        .last("LIMIT 100"));
        Collections.reverse(messages);
        return messages.stream().map(message -> {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("id", message.getId());
            item.put("role", message.getRole());
            item.put("content", message.getContent());
            item.put("plans", readJsonList(message.getPlansJson()));
            item.put("hotelOptions", readJsonList(message.getHotelOptionsJson()));
            item.put("changed", Integer.valueOf(1).equals(message.getChanged()));
            item.put("baseRevision", actionBaseRevision(message));
            item.put("createdAt", message.getCreatedAt());
            return item;
        }).toList();
    }

    @Transactional
    public void clearChatHistory(Long userId, Long itineraryId) {
        queryService.findOwnedMain(userId, itineraryId);
        chatMessageMapper.delete(new LambdaQueryWrapper<ItineraryChatMessage>()
                .eq(ItineraryChatMessage::getItineraryId, itineraryId)
                .eq(ItineraryChatMessage::getUserId, userId));
    }

    public ItineraryChatMessage requirePendingAction(Long userId, Long itineraryId,
                                                      Long messageId, String baseRevision,
                                                      boolean hotelAction) {
        if (messageId == null || baseRevision == null || baseRevision.isBlank()) {
            throw new BizException(409, "该方案缺少版本信息，请重新生成后再应用");
        }
        ItineraryChatMessage message = chatMessageMapper.selectOne(
                new LambdaQueryWrapper<ItineraryChatMessage>()
                        .eq(ItineraryChatMessage::getId, messageId)
                        .eq(ItineraryChatMessage::getItineraryId, itineraryId)
                        .eq(ItineraryChatMessage::getUserId, userId)
                        .eq(ItineraryChatMessage::getRole, "ai")
                        .last("LIMIT 1"));
        List<Object> payload = message == null ? List.of() : readJsonList(
                hotelAction ? message.getHotelOptionsJson() : message.getPlansJson());
        if (message == null || payload.isEmpty()) {
            throw new BizException(409, "该方案已失效，请使用最新建议");
        }
        ItineraryChatMessage latest = chatMessageMapper.selectList(
                        new LambdaQueryWrapper<ItineraryChatMessage>()
                                .eq(ItineraryChatMessage::getItineraryId, itineraryId)
                                .eq(ItineraryChatMessage::getUserId, userId)
                                .eq(ItineraryChatMessage::getRole, "ai")
                                .orderByDesc(ItineraryChatMessage::getId))
                .stream().filter(this::hasActionPayload).findFirst().orElse(null);
        if (latest == null || !latest.getId().equals(message.getId())) {
            throw new BizException(409, "该方案已被更新的建议取代，请使用最新方案");
        }
        String currentRevision = planRevision(currentPlans(itineraryId));
        if (!baseRevision.equals(actionBaseRevision(message)) || !baseRevision.equals(currentRevision)) {
            consumePendingAction(message);
            throw new BizException(409, "行程已发生变化，该方案已失效，请重新生成建议");
        }
        return message;
    }

    public void validateHotelChoice(ItineraryChatMessage message, String hotelName, String roomName) {
        for (Object rawOption : readJsonList(message.getHotelOptionsJson())) {
            if (!(rawOption instanceof Map<?, ?> option)
                    || !hotelName.equals(String.valueOf(option.get("hotelName")))) {
                continue;
            }
            Object rawRooms = option.get("roomTypes");
            if (rawRooms instanceof List<?> rooms && rooms.stream().anyMatch(rawRoom ->
                    rawRoom instanceof Map<?, ?> room
                            && roomName.equals(String.valueOf(room.get("roomName"))))) {
                return;
            }
        }
        throw new BizException(409, "所选酒店或房型不属于当前有效方案，请重新获取建议");
    }

    public void invalidatePendingActions(Long userId, Long itineraryId) {
        List<ItineraryChatMessage> messages = chatMessageMapper.selectList(
                new LambdaQueryWrapper<ItineraryChatMessage>()
                        .eq(ItineraryChatMessage::getItineraryId, itineraryId)
                        .eq(ItineraryChatMessage::getUserId, userId)
                        .eq(ItineraryChatMessage::getRole, "ai"));
        for (ItineraryChatMessage message : messages) {
            if (hasActionPayload(message)) {
                consumePendingAction(message);
            }
        }
    }

    public void consumePendingAction(ItineraryChatMessage message) {
        message.setPlansJson("[]");
        message.setHotelOptionsJson("[]");
        message.setChanged(0);
        chatMessageMapper.updateById(message);
    }

    @SuppressWarnings("unchecked")
    public List<Map<String, Object>> readPlans(ItineraryChatMessage message) {
        return readJsonList(message.getPlansJson()).stream()
                .map(row -> (Map<String, Object>) objectMapper.convertValue(row, Map.class))
                .toList();
    }

    private ItineraryChatMessage saveChatMessage(Long userId, Long itineraryId, String role, String content,
                                                 List<?> plans, List<?> hotelOptions, boolean changed) {
        ItineraryChatMessage message = new ItineraryChatMessage();
        message.setItineraryId(itineraryId);
        message.setUserId(userId);
        message.setRole(role);
        message.setContent(content == null ? "" : content);
        message.setPlansJson(writeJson(plans));
        message.setHotelOptionsJson(writeJson(hotelOptions));
        message.setChanged(changed ? 1 : 0);
        chatMessageMapper.insert(message);
        return message;
    }

    private List<Map<String, Object>> currentPlans(Long itineraryId) {
        List<Map<String, Object>> plans = new ArrayList<>();
        List<ItineraryDay> days = dayMapper.selectList(new LambdaQueryWrapper<ItineraryDay>()
                .eq(ItineraryDay::getItineraryId, itineraryId).orderByAsc(ItineraryDay::getDayNo));
        List<ItineraryItem> allItems = itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                .eq(ItineraryItem::getItineraryId, itineraryId)
                .orderByAsc(ItineraryItem::getDayId).orderByAsc(ItineraryItem::getSortNo));
        Map<Long, List<ItineraryItem>> itemsByDay = allItems.stream()
                .collect(java.util.stream.Collectors.groupingBy(ItineraryItem::getDayId));
        for (ItineraryDay day : days) {
            List<Map<String, Object>> items = new ArrayList<>();
            for (ItineraryItem item : itemsByDay.getOrDefault(day.getId(), List.of())) {
                Map<String, Object> im = new LinkedHashMap<>();
                im.put("id", item.getId());
                im.put("item_type", item.getItemType());
                im.put("poi_name", item.getPoiName());
                im.put("poi_id", item.getPoiId());
                im.put("address", item.getAddress());
                im.put("latitude", item.getLatitude());
                im.put("longitude", item.getLongitude());
                im.put("start_time", item.getStartTime() == null ? null : item.getStartTime().toString());
                im.put("end_time", item.getEndTime() == null ? null : item.getEndTime().toString());
                im.put("duration_min", item.getDurationMin());
                im.put("cost", item.getCost());
                im.put("tag", item.getTag());
                im.put("remark", item.getRemark());
                im.put("sort_no", item.getSortNo());
                items.add(im);
            }
            Map<String, Object> plan = new LinkedHashMap<>();
            plan.put("day_no", day.getDayNo());
            plan.put("note", day.getNote());
            plan.put("items", items);
            plans.add(plan);
        }
        return plans;
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> latestPendingPlans(Long userId, Long itineraryId, String baseRevision) {
        return chatMessageMapper.selectList(new LambdaQueryWrapper<ItineraryChatMessage>()
                        .eq(ItineraryChatMessage::getItineraryId, itineraryId)
                        .eq(ItineraryChatMessage::getUserId, userId)
                        .eq(ItineraryChatMessage::getRole, "ai")
                        .eq(ItineraryChatMessage::getChanged, 1)
                        .orderByDesc(ItineraryChatMessage::getId))
                .stream()
                .filter(message -> baseRevision.equals(actionBaseRevision(message)))
                .findFirst()
                .map(message -> readJsonList(message.getPlansJson()).stream()
                        .map(row -> (Map<String, Object>) objectMapper.convertValue(row, Map.class))
                        .toList())
                .orElse(List.of());
    }

    private String planRevision(List<Map<String, Object>> plans) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(writeJson(plans).getBytes(StandardCharsets.UTF_8));
            return java.util.HexFormat.of().formatHex(digest);
        } catch (java.security.NoSuchAlgorithmException e) {
            throw new BizException(500, "无法生成行程版本标识");
        }
    }

    private List<Object> attachBaseRevision(List<Object> rows, String baseRevision, boolean camelCase) {
        List<Object> result = new ArrayList<>();
        for (Object row : rows) {
            Map<String, Object> map = objectMapper.convertValue(row, LinkedHashMap.class);
            map.put(camelCase ? "baseRevision" : "_baseRevision", baseRevision);
            result.add(map);
        }
        return result;
    }

    private boolean hasActionPayload(ItineraryChatMessage message) {
        return Integer.valueOf(1).equals(message.getChanged())
                || !readJsonList(message.getPlansJson()).isEmpty()
                || !readJsonList(message.getHotelOptionsJson()).isEmpty();
    }

    private String actionBaseRevision(ItineraryChatMessage message) {
        List<Object> plans = readJsonList(message.getPlansJson());
        if (!plans.isEmpty() && plans.get(0) instanceof Map<?, ?> map) {
            Object revision = map.get("_baseRevision");
            return revision == null ? null : String.valueOf(revision);
        }
        List<Object> options = readJsonList(message.getHotelOptionsJson());
        if (!options.isEmpty() && options.get(0) instanceof Map<?, ?> map) {
            Object revision = map.get("baseRevision");
            return revision == null ? null : String.valueOf(revision);
        }
        return null;
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value == null ? List.of() : value);
        } catch (tools.jackson.core.JacksonException e) {
            throw new BizException(500, "保存对话上下文失败");
        }
    }

    private List<Object> readJsonList(String value) {
        if (value == null || value.isBlank()) {
            return List.of();
        }
        try {
            return objectMapper.readValue(value,
                    objectMapper.getTypeFactory().constructCollectionType(List.class, Object.class));
        } catch (tools.jackson.core.JacksonException e) {
            return List.of();
        }
    }

    private List<Object> objectMapperTreeList(JsonNode arr) {
        List<Object> list = new ArrayList<>();
        if (arr != null && arr.isArray()) {
            arr.forEach(list::add);
        }
        return list;
    }
}
