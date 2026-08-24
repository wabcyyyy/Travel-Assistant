package com.travel.backend.service;

import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.dto.ItemUpsertRequest;
import com.travel.backend.vo.ItinerarySummaryVO;
import com.travel.backend.vo.ItineraryVO;

import java.util.List;
import java.util.Map;

public interface ItineraryService {

    ItineraryVO generate(Long userId, GenerateRequest request);

    List<ItinerarySummaryVO> list(Long userId);

    ItineraryVO detail(Long userId, Long id);

    void delete(Long userId, Long id);

    ItineraryVO addItem(Long userId, Long itineraryId, ItemUpsertRequest request);

    ItineraryVO updateItem(Long userId, Long itemId, ItemUpsertRequest request);

    ItineraryVO deleteItem(Long userId, Long itemId);

    ItineraryVO reorderItems(Long userId, Long itineraryId, Long dayId, List<Long> itemIds);

    Map<String, Object> nlEdit(Long userId, Long itineraryId, String instruction);

    Map<String, Object> clarify(String message, Map<String, Object> slots);
}