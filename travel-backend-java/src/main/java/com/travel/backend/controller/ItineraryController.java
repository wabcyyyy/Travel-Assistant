package com.travel.backend.controller;

import com.travel.backend.common.Result;
import com.travel.backend.common.SecurityUtils;
import com.travel.backend.dto.GenerateRequest;
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

@RestController
@RequestMapping("/api/itinerary")
public class ItineraryController {

    private final ItineraryService itineraryService;
    private final UserService userService;

    public ItineraryController(ItineraryService itineraryService, UserService userService) {
        this.itineraryService = itineraryService;
        this.userService = userService;
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

    private Long currentUserId() {
        return userService.getByUsername(SecurityUtils.currentUsername()).getId();
    }
}