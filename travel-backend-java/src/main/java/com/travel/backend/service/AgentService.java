package com.travel.backend.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.travel.backend.dto.AgentGenerateRequest;
import com.travel.backend.dto.AgentGenerateResponse;

import java.util.List;
import java.util.Map;

public interface AgentService {

    AgentGenerateResponse generate(AgentGenerateRequest request);

    JsonNode clarify(String message, Map<String, Object> slots);

    JsonNode editOps(String city, int days, List<Map<String, Object>> plans, String instruction);

    JsonNode chatTurn(Map<String, Object> payload);
}