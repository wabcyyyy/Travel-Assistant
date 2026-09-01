package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
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
        JsonNode node = agentService.cityGuide(Map.of(
                "input", input == null ? "" : input,
                "supported", supportedCities(),
                "history", history == null ? List.of() : history));
        Map<String, Object> result = new HashMap<>();
        result.put("kind", node.path("kind").asText("unclear"));
        result.put("city", node.hasNonNull("city") ? node.get("city").asText() : null);
        result.put("message", node.path("message").asText("想去哪里玩？说说你的想法～"));
        List<Map<String, Object>> suggestions = new ArrayList<>();
        node.path("suggestions").forEach(suggestion -> {
            if (suggestion.hasNonNull("name")) {
                suggestions.add(Map.of("name", suggestion.get("name").asText(),
                        "reason", suggestion.path("reason").asText("")));
            }
        });
        result.put("suggestions", suggestions);
        return result;
    }

    public Map<String, Object> clarify(String message, Map<String, Object> slots) {
        JsonNode node = agentService.clarify(message, slots);
        Map<String, Object> result = new HashMap<>();
        result.put("slots", node.get("slots"));
        result.put("missing", node.get("missing"));
        result.put("question", node.path("question").asText(null));
        result.put("ready", node.path("ready").asBoolean(false));
        return result;
    }
}
