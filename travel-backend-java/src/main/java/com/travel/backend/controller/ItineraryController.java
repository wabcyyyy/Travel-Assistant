package com.travel.backend.controller;

import com.travel.backend.common.Result;
import com.travel.backend.common.SecurityUtils;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.dto.HotelOptionApplyRequest;
import com.travel.backend.dto.ItemUpsertRequest;
import com.travel.backend.service.ItineraryService;
import com.travel.backend.service.UserService;
import com.travel.backend.vo.ItinerarySummaryVO;
import com.travel.backend.vo.ItineraryVO;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/itinerary")
public class ItineraryController {

    private final ItineraryService itineraryService;
    private final UserService userService;

    public ItineraryController(ItineraryService itineraryService, UserService userService) {
        this.itineraryService = itineraryService;
        this.userService = userService;
    }

    @GetMapping("/supported-cities")
    public Result<List<String>> supportedCities() {
        return Result.ok(itineraryService.supportedCities());
    }

    @PostMapping("/generate")
    public Result<ItineraryVO> generate(@Valid @RequestBody GenerateRequest request) {
        return Result.ok(itineraryService.generate(currentUserId(), request));
    }

    @GetMapping
    public Result<List<ItinerarySummaryVO>> list() {
        return Result.ok(itineraryService.list(currentUserId()));
    }

    @GetMapping("/{id}")
    public Result<ItineraryVO> detail(@PathVariable Long id) {
        return Result.ok(itineraryService.detail(currentUserId(), id));
    }

    @DeleteMapping("/{id}")
    public Result<Void> delete(@PathVariable Long id) {
        itineraryService.delete(currentUserId(), id);
        return Result.ok();
    }

    @PostMapping("/{id}/items")
    public Result<ItineraryVO> addItem(@PathVariable Long id,
                                       @RequestBody ItemUpsertRequest request) {
        return Result.ok(itineraryService.addItem(currentUserId(), id, request));
    }

    @PutMapping("/items/{itemId}")
    public Result<ItineraryVO> updateItem(@PathVariable Long itemId,
                                          @RequestBody ItemUpsertRequest request) {
        return Result.ok(itineraryService.updateItem(currentUserId(), itemId, request));
    }

    @DeleteMapping("/items/{itemId}")
    public Result<ItineraryVO> deleteItem(@PathVariable Long itemId) {
        return Result.ok(itineraryService.deleteItem(currentUserId(), itemId));
    }

    @PutMapping("/{id}/days/{dayId}/order")
    public Result<ItineraryVO> reorderItems(@PathVariable Long id,
                                            @PathVariable Long dayId,
                                            @RequestBody List<Long> itemIds) {
        return Result.ok(itineraryService.reorderItems(currentUserId(), id, dayId, itemIds));
    }

    @PostMapping("/clarify")
    public Result<Map<String, Object>> clarify(@RequestBody Map<String, Object> body) {
        String message = String.valueOf(body.getOrDefault("message", ""));
        @SuppressWarnings("unchecked")
        Map<String, Object> slots = (Map<String, Object>) body.getOrDefault("slots", Map.of());
        return Result.ok(itineraryService.clarify(message, slots));
    }

    @PostMapping("/{id}/nl-edit")
    public Result<Map<String, Object>> nlEdit(@PathVariable Long id,
                                              @RequestBody Map<String, String> body) {
        return Result.ok(itineraryService.nlEdit(currentUserId(), id,
                body.getOrDefault("instruction", "")));
    }

    @PostMapping("/{id}/chat-edit")
    public Result<Map<String, Object>> chatEdit(@PathVariable Long id,
                                                @RequestBody Map<String, Object> body) {
        String message = String.valueOf(body.getOrDefault("message", ""));
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> history =
                (List<Map<String, Object>>) body.getOrDefault("history", List.of());
        return Result.ok(itineraryService.chatEdit(currentUserId(), id, message, history));
    }

    @GetMapping("/{id}/chat-history")
    public Result<List<Map<String, Object>>> chatHistory(@PathVariable Long id) {
        return Result.ok(itineraryService.chatHistory(currentUserId(), id));
    }

    @DeleteMapping("/{id}/chat-history")
    public Result<Void> clearChatHistory(@PathVariable Long id) {
        itineraryService.clearChatHistory(currentUserId(), id);
        return Result.ok();
    }

    @SuppressWarnings("unchecked")
    @PostMapping("/{id}/apply-plans")
    public Result<ItineraryVO> applyPlans(@PathVariable Long id,
                                          @RequestBody Map<String, Object> body) {
        List<Map<String, Object>> plans =
                (List<Map<String, Object>>) body.getOrDefault("plans", List.of());
        Long actionMessageId = body.get("actionMessageId") instanceof Number number
                ? number.longValue() : null;
        String baseRevision = body.get("baseRevision") == null
                ? null : String.valueOf(body.get("baseRevision"));
        return Result.ok(itineraryService.applyPlans(
                currentUserId(), id, plans, actionMessageId, baseRevision));
    }

    @PostMapping("/{id}/hotel-option")
    public Result<ItineraryVO> applyHotelOption(@PathVariable Long id,
                                                @Valid @RequestBody HotelOptionApplyRequest request) {
        return Result.ok(itineraryService.applyHotelOption(currentUserId(), id, request));
    }

    private Long currentUserId() {
        return userService.getByUsername(SecurityUtils.currentUsername()).getId();
    }
}
