package com.travel.backend.service;

import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.vo.ItinerarySummaryVO;
import com.travel.backend.vo.ItineraryVO;

import java.util.List;

public interface ItineraryService {

    ItineraryVO generate(Long userId, GenerateRequest request);

    List<ItinerarySummaryVO> list(Long userId);

    ItineraryVO detail(Long userId, Long id);

    void delete(Long userId, Long id);
}