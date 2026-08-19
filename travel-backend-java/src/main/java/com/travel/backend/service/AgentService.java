package com.travel.backend.service;

import com.travel.backend.dto.AgentGenerateRequest;
import com.travel.backend.dto.AgentGenerateResponse;

public interface AgentService {

    AgentGenerateResponse generate(AgentGenerateRequest request);
}