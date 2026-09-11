package com.travel.backend.serviceImpl;

import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.dto.HotelOptionApplyRequest;
import com.travel.backend.dto.ItemUpsertRequest;
import com.travel.backend.service.ItineraryService;
import com.travel.backend.vo.ItinerarySummaryVO;
import com.travel.backend.vo.ItineraryVO;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

/**
 * 行程管理业务门面（Facade）。
 *
 * <p>对外保持 {@link ItineraryService} 契约不变，内部按领域拆分委托给子服务：</p>
 * <ul>
 *   <li>{@link ItineraryGenerationService} — 行程生成（建壳 + 异步编排）</li>
 *   <li>{@link ItineraryQueryService} — 行程查询（列表 / 详情 / 缓存）</li>
 *   <li>{@link ItineraryCommandService} — 行程项 CRUD + 排序 + 自然语言编辑</li>
 *   <li>{@link ItineraryCityService} — 澄清 / 城市引导 / 支持城市列表</li>
 *   <li>{@link ItineraryChatService} — 对话编辑 / 历史管理</li>
 *   <li>{@link ItineraryPlanApplyService} — 草稿应用 / 酒店选项应用</li>
 *   <li>{@link UserPreferenceService} — 用户偏好统计与推荐</li>
 * </ul>
 *
 * <p>Controller 无需感知内部重构，所有子服务对前端透明。</p>
 *
 * @see ItineraryGenerationService
 * @see ItineraryChatService
 * @see ItineraryPlanApplyService
 */
@Service
public class ItineraryServiceImpl implements ItineraryService {

    private final ItineraryGenerationService generationService;
    private final ItineraryQueryService queryService;
    private final ItineraryCommandService commandService;
    private final ItineraryCityService cityService;
    private final ItineraryChatService chatService;
    private final ItineraryPlanApplyService planApplyService;
    private final UserPreferenceService preferenceService;
    private final ItineraryVersionService versionService;

    public ItineraryServiceImpl(ItineraryGenerationService generationService,
                                ItineraryQueryService queryService,
                                ItineraryCommandService commandService,
                                ItineraryCityService cityService,
                                ItineraryChatService chatService,
                                ItineraryPlanApplyService planApplyService,
                                UserPreferenceService preferenceService,
                                ItineraryVersionService versionService) {
        this.generationService = generationService;
        this.queryService = queryService;
        this.commandService = commandService;
        this.cityService = cityService;
        this.chatService = chatService;
        this.planApplyService = planApplyService;
        this.preferenceService = preferenceService;
        this.versionService = versionService;
    }

    @Override
    public ItineraryVO generate(Long userId, GenerateRequest request) {
        return generationService.generate(userId, request);
    }

    @Override
    public List<ItinerarySummaryVO> list(Long userId) {
        return queryService.list(userId);
    }

    @Override
    public ItineraryVO detail(Long userId, Long id) {
        return queryService.detail(userId, id);
    }

    @Override
    public void delete(Long userId, Long id) {
        commandService.delete(userId, id);
    }

    @Override
    public ItineraryVO addItem(Long userId, Long itineraryId, ItemUpsertRequest request) {
        return commandService.addItem(userId, itineraryId, request);
    }

    @Override
    public ItineraryVO updateItem(Long userId, Long itemId, ItemUpsertRequest request) {
        return commandService.updateItem(userId, itemId, request);
    }

    @Override
    public ItineraryVO deleteItem(Long userId, Long itemId) {
        return commandService.deleteItem(userId, itemId);
    }

    @Override
    public ItineraryVO reorderItems(Long userId, Long itineraryId, Long dayId, List<Long> itemIds) {
        return commandService.reorderItems(userId, itineraryId, dayId, itemIds);
    }

    @Override
    public Map<String, Object> nlEdit(Long userId, Long itineraryId, String instruction) {
        return commandService.nlEdit(userId, itineraryId, instruction);
    }

    @Override
    public Map<String, Object> clarify(String message, Map<String, Object> slots) {
        return cityService.clarify(message, slots);
    }

    @Override
    public Map<String, Object> chatEdit(Long userId, Long itineraryId, String message,
                                        List<Map<String, Object>> history) {
        return chatService.chatEdit(userId, itineraryId, message, history);
    }

    @Override
    public List<Map<String, Object>> chatHistory(Long userId, Long itineraryId) {
        return chatService.chatHistory(userId, itineraryId);
    }

    @Override
    public void clearChatHistory(Long userId, Long itineraryId) {
        chatService.clearChatHistory(userId, itineraryId);
    }

    @Override
    public ItineraryVO applyPlans(Long userId, Long itineraryId, List<Map<String, Object>> plans,
                                  Long actionMessageId, String baseRevision) {
        return planApplyService.applyPlans(userId, itineraryId, actionMessageId, baseRevision);
    }

    @Override
    public ItineraryVO applyHotelOption(Long userId, Long itineraryId, HotelOptionApplyRequest request) {
        return planApplyService.applyHotelOption(userId, itineraryId, request);
    }

    @Override
    public List<String> supportedCities() {
        return cityService.supportedCities();
    }

    @Override
    public Map<String, Object> cityGuide(String input, List<Map<String, Object>> history) {
        return cityService.cityGuide(input, history);
    }

    @Override
    public Map<String, Object> poiNearby(Map<String, Object> payload) {
        return cityService.poiNearby(payload);
    }

    @Override
    public List<String> topPreferences(Long userId, int limit) {
        return preferenceService.topPreferences(userId, limit);
    }

    @Override
    public void recordPreferences(Long userId, List<String> preferences) {
        preferenceService.recordPreferences(userId, preferences);
    }

    @Override
    public void recordPreferenceSignals(Long userId, List<String> explicit, List<String> hard,
                                        List<String> negative, String source, double confidence) {
        preferenceService.recordSignals(userId, explicit, hard, negative, source, confidence);
    }

    @Override
    public List<Map<String, Object>> preferenceSignals(Long userId, int limit) {
        return preferenceService.signals(userId, limit);
    }

    @Override
    public Map<String, Object> createVersion(Long userId, Long itineraryId, String operation, String summary) {
        return versionService.createSnapshot(userId, itineraryId, operation, summary);
    }

    @Override
    public List<Map<String, Object>> listVersions(Long userId, Long itineraryId) {
        return versionService.list(userId, itineraryId);
    }

    @Override
    public Map<String, Object> diffVersions(Long userId, Long itineraryId, Long fromVersionId, Long toVersionId) {
        return versionService.diff(userId, itineraryId, fromVersionId, toVersionId);
    }

    @Override
    public ItineraryVO restoreVersion(Long userId, Long itineraryId, Long versionId) {
        return versionService.restore(userId, itineraryId, versionId);
    }
}
