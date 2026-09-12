package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.travel.backend.dto.AgentCityGuideMessage;
import com.travel.backend.dto.AgentCityGuideRequest;
import com.travel.backend.dto.AgentCityGuideResponse;
import com.travel.backend.dto.AgentClarifyRequest;
import com.travel.backend.dto.AgentClarifyResponse;
import com.travel.backend.dto.AgentPoiNearbyItem;
import com.travel.backend.dto.AgentPoiNearbyRequest;
import com.travel.backend.dto.AgentPoiNearbyResponse;
import com.travel.backend.entity.PoiKnowledge;
import com.travel.backend.mapper.PoiKnowledgeMapper;
import com.travel.backend.service.AgentService;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** 城市能力发现、城市引导和行程生成前的澄清问答。 */
@Service
public class ItineraryCityService {

    private final PoiKnowledgeMapper poiKnowledgeMapper;
    private final AgentService agentService;

    public ItineraryCityService(PoiKnowledgeMapper poiKnowledgeMapper, AgentService agentService) {
        this.poiKnowledgeMapper = poiKnowledgeMapper;
        this.agentService = agentService;
    }

    public List<String> supportedCities() {
        return poiKnowledgeMapper.selectList(new LambdaQueryWrapper<PoiKnowledge>()
                        .select(true, PoiKnowledge::getCity))
                .stream()
                .map(PoiKnowledge::getCity)
                .filter(city -> city != null && !city.isBlank())
                .distinct()
                .sorted()
                .toList();
    }

    public Map<String, Object> cityGuide(String input, List<Map<String, Object>> history) {
        AgentCityGuideRequest request = new AgentCityGuideRequest();
        request.setInput(input == null ? "" : input);
        request.setSupported(supportedCities());
        request.setHistory(toGuideHistory(history));
        AgentCityGuideResponse response = agentService.cityGuide(request);
        Map<String, Object> result = new HashMap<>();
        result.put("kind", response.getKind() == null ? "unclear" : response.getKind());
        result.put("city", response.getCity());
        result.put("message", response.getMessage() == null ? "想去哪里玩？说说你的想法～" : response.getMessage());
        List<Map<String, Object>> suggestions = new ArrayList<>();
        if (response.getSuggestions() != null) {
            response.getSuggestions().forEach(suggestion -> {
                if (suggestion.getName() != null) {
                    suggestions.add(Map.of("name", suggestion.getName(),
                            "reason", suggestion.getReason() == null ? "" : suggestion.getReason()));
                }
            });
        }
        result.put("suggestions", suggestions);
        return result;
    }

    /**
     * 同城权威 POI 近邻（附近推荐）：payload 透传给 Python Agent 的 /v1/poi-nearby。
     * 返回 items 列表（name/category/rating/address/distanceM 等）。
     */
    public Map<String, Object> poiNearby(Map<String, Object> payload) {
        Map<String, Object> source = payload == null ? Map.of() : payload;
        AgentPoiNearbyRequest request = new AgentPoiNearbyRequest();
        request.setCity(asString(source.get("city")));
        request.setName(asString(source.get("name")));
        request.setLatitude(asDouble(source.get("latitude")));
        request.setLongitude(asDouble(source.get("longitude")));
        request.setLimit(asInteger(source.get("limit")));
        // 历史调用方存在 snake_case 与 camelCase 两种键，两者都尝试取
        Object radius = source.get("radiusM") != null ? source.get("radiusM") : source.get("radius_m");
        request.setRadiusM(asInteger(radius));
        request.setCategory(asString(source.get("category")));
        AgentPoiNearbyResponse response = agentService.poiNearby(request);
        Map<String, Object> result = new HashMap<>();
        List<Map<String, Object>> items = new ArrayList<>();
        if (response.getItems() != null) {
            response.getItems().forEach(item -> items.add(toNearbyRow(item)));
        }
        result.put("items", items);
        return result;
    }

    public Map<String, Object> clarify(String message, Map<String, Object> slots) {
        AgentClarifyRequest request = new AgentClarifyRequest();
        request.setMessage(message);
        request.setSlots(slots);
        AgentClarifyResponse response = agentService.clarify(request);
        Map<String, Object> result = new HashMap<>();
        result.put("slots", response.getSlots());
        result.put("missing", response.getMissing());
        result.put("question", response.getQuestion());
        result.put("ready", Boolean.TRUE.equals(response.getReady()));
        return result;
    }

    /** 前端对话历史（{role, content}）转为 Agent 契约的强类型条目。 */
    private List<AgentCityGuideMessage> toGuideHistory(List<Map<String, Object>> history) {
        if (history == null) {
            return List.of();
        }
        List<AgentCityGuideMessage> messages = new ArrayList<>();
        for (Map<String, Object> row : history) {
            AgentCityGuideMessage message = new AgentCityGuideMessage();
            message.setRole(asString(row.get("role")));
            message.setContent(asString(row.get("content")));
            messages.add(message);
        }
        return messages;
    }

    /** 重组为前端契约的 Map：键 name/category/rating/address/distanceM（camelCase）。 */
    private Map<String, Object> toNearbyRow(AgentPoiNearbyItem item) {
        Map<String, Object> row = new HashMap<>();
        row.put("name", item.getName() == null ? "" : item.getName());
        row.put("category", item.getCategory() == null ? "attraction" : item.getCategory());
        row.put("rating", item.getRating());
        row.put("address", item.getAddress());
        row.put("distanceM", item.getDistanceM());
        return row;
    }

    private static String asString(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private static Double asDouble(Object value) {
        if (value instanceof Number number) {
            return number.doubleValue();
        }
        if (value instanceof String text && !text.isBlank()) {
            try {
                return Double.parseDouble(text.trim());
            } catch (NumberFormatException ignored) {
                return null;
            }
        }
        return null;
    }

    private static Integer asInteger(Object value) {
        if (value instanceof Number number) {
            return number.intValue();
        }
        if (value instanceof String text && !text.isBlank()) {
            try {
                return Integer.parseInt(text.trim());
            } catch (NumberFormatException ignored) {
                return null;
            }
        }
        return null;
    }
}
