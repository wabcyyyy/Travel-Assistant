package com.travel.backend.controller;

import com.travel.backend.common.Result;
import com.travel.backend.common.SecurityUtils;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.dto.HotelOptionApplyRequest;
import com.travel.backend.dto.ItemUpsertRequest;
import com.travel.backend.dto.PreferenceSignalRequest;
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

/**
 * 行程管理 REST 控制器。
 *
 * <p>提供行程的完整 API，包括 CRUD、对话编辑、草稿应用、城市引导等。
 * 所有接口均需 JWT 鉴权（通过 SecurityUtils 获取当前用户）。</p>
 *
 * <p>端点前缀：{@code /api/itinerary}</p>
 *
 * @see ItineraryService
 */
@RestController
@RequestMapping("/api/itinerary")
public class ItineraryController {

    private final ItineraryService itineraryService;
    private final UserService userService;

    public ItineraryController(ItineraryService itineraryService, UserService userService) {
        this.itineraryService = itineraryService;
        this.userService = userService;
    }

    /** 获取支持的目的地城市列表（知识库中有 POI 数据的城市）。 */
    @GetMapping("/supported-cities")
    public Result<List<String>> supportedCities() {
        return Result.ok(itineraryService.supportedCities());
    }

    /** 城市引导对话：用户不确定去哪时，AI 根据偏好推荐城市。 */
    @PostMapping("/city-guide")
    public Result<Map<String, Object>> cityGuide(@RequestBody Map<String, Object> body) {
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> history =
                (List<Map<String, Object>>) body.getOrDefault("history", List.of());
        return Result.ok(itineraryService.cityGuide(
                String.valueOf(body.getOrDefault("input", "")), history));
    }

    /** 附近推荐：行程项所在城市的权威知识库真实近邻（轻量 GraphRAG）。 */
    @PostMapping("/poi-nearby")
    public Result<Map<String, Object>> poiNearby(@RequestBody Map<String, Object> body) {
        return Result.ok(itineraryService.poiNearby(body));
    }

    /**
     * 生成行程：建壳 → 异步逐日生成 → 返回初始状态（status=1）。
     *
     * <p>前端收到响应后应轮询 GET /{id} 查看渐进结果。</p>
     */
    @PostMapping("/generate")
    public Result<ItineraryVO> generate(@Valid @RequestBody GenerateRequest request) {
        return Result.ok(itineraryService.generate(currentUserId(), request));
    }

    /** 查询用户行程列表（按创建时间倒序）。 */
    @GetMapping
    public Result<List<ItinerarySummaryVO>> list() {
        return Result.ok(itineraryService.list(currentUserId()));
    }

    /** 查询行程详情（含日行程 + 行程项 + 预算）。 */
    @GetMapping("/{id}")
    public Result<ItineraryVO> detail(@PathVariable Long id) {
        return Result.ok(itineraryService.detail(currentUserId(), id));
    }

    /** 删除行程（逻辑删除）。 */
    @DeleteMapping("/{id}")
    public Result<Void> delete(@PathVariable Long id) {
        itineraryService.delete(currentUserId(), id);
        return Result.ok();
    }

    /** 新增行程项（景点/餐饮/酒店/交通）。 */
    @PostMapping("/{id}/items")
    public Result<ItineraryVO> addItem(@PathVariable Long id,
                                       @RequestBody ItemUpsertRequest request) {
        return Result.ok(itineraryService.addItem(currentUserId(), id, request));
    }

    /** 更新行程项（时间/费用/标签等）。 */
    @PutMapping("/items/{itemId}")
    public Result<ItineraryVO> updateItem(@PathVariable Long itemId,
                                          @RequestBody ItemUpsertRequest request) {
        return Result.ok(itineraryService.updateItem(currentUserId(), itemId, request));
    }

    /** 删除行程项。 */
    @DeleteMapping("/items/{itemId}")
    public Result<ItineraryVO> deleteItem(@PathVariable Long itemId) {
        return Result.ok(itineraryService.deleteItem(currentUserId(), itemId));
    }

    /** 拖拽排序：指定日内行程项的顺序。 */
    @PutMapping("/{id}/days/{dayId}/order")
    public Result<ItineraryVO> reorderItems(@PathVariable Long id,
                                            @PathVariable Long dayId,
                                            @RequestBody List<Long> itemIds) {
        return Result.ok(itineraryService.reorderItems(currentUserId(), id, dayId, itemIds));
    }

    /**
     * 槽位澄清：从用户输入中抽取行程参数，返回缺失字段和追问。
     *
     * <p>纯透传 Python Agent 的 clarify 接口，Java 侧不存储槽位状态。</p>
     */
    @PostMapping("/clarify")
    public Result<Map<String, Object>> clarify(@RequestBody Map<String, Object> body) {
        String message = String.valueOf(body.getOrDefault("message", ""));
        @SuppressWarnings("unchecked")
        Map<String, Object> slots = (Map<String, Object>) body.getOrDefault("slots", Map.of());
        return Result.ok(itineraryService.clarify(message, slots));
    }

    /**
     * 自然语言编辑：解析指令并执行操作（删除/新增/移动等）。
     *
     * <p>与 chatEdit 的区别：nlEdit 直接执行操作并落库，chatEdit 只返回草稿。</p>
     */
    @PostMapping("/{id}/nl-edit")
    public Result<Map<String, Object>> nlEdit(@PathVariable Long id,
                                              @RequestBody Map<String, String> body) {
        return Result.ok(itineraryService.nlEdit(currentUserId(), id,
                body.getOrDefault("instruction", "")));
    }

    /**
     * 对话编辑：基于当前行程 + 用户消息，返回草稿方案（不落库）。
     *
     * <p>前端收到草稿后展示预览，用户点击"应用到行程"后调用 apply-plans 落库。</p>
     */
    @PostMapping("/{id}/chat-edit")
    public Result<Map<String, Object>> chatEdit(@PathVariable Long id,
                                                @RequestBody Map<String, Object> body) {
        String message = String.valueOf(body.getOrDefault("message", ""));
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> history =
                (List<Map<String, Object>>) body.getOrDefault("history", List.of());
        return Result.ok(itineraryService.chatEdit(currentUserId(), id, message, history));
    }

    /** 获取对话历史（按时间正序）。 */
    @GetMapping("/{id}/chat-history")
    public Result<List<Map<String, Object>>> chatHistory(@PathVariable Long id) {
        return Result.ok(itineraryService.chatHistory(currentUserId(), id));
    }

    /** 清空对话历史。 */
    @DeleteMapping("/{id}/chat-history")
    public Result<Void> clearChatHistory(@PathVariable Long id) {
        itineraryService.clearChatHistory(currentUserId(), id);
        return Result.ok();
    }

    /**
     * 应用草稿方案：校验版本一致性（baseRevision）→ 事务内逐项落库。
     *
     * <p>只接受从 chat-edit 返回的 baseRevision，防止旧草稿覆盖新数据。</p>
     */
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

    /**
     * 应用酒店选项：校验房型价格 → 季节因子调整 → 逐晚插入/更新。
     *
     * <p>从对话编辑产生的酒店候选卡片中选择后调用。</p>
     */
    @PostMapping("/{id}/hotel-option")
    public Result<ItineraryVO> applyHotelOption(@PathVariable Long id,
                                                @Valid @RequestBody HotelOptionApplyRequest request) {
        return Result.ok(itineraryService.applyHotelOption(currentUserId(), id, request));
    }

    /** 获取用户偏好 top 5（按选择次数降序）。 */
    @GetMapping("/preferences")
    public Result<List<String>> topPreferences() {
        return Result.ok(itineraryService.topPreferences(currentUserId(), 5));
    }

    @PostMapping("/preferences/signals")
    public Result<Void> preferenceSignals(@Valid @RequestBody PreferenceSignalRequest request) {
        itineraryService.recordPreferenceSignals(currentUserId(), request.getExplicitPreferences(),
                request.getHardConstraints(), request.getNegativePreferences(), request.getSource(),
                request.getConfidence() == null ? 1.0 : request.getConfidence());
        return Result.ok();
    }

    @GetMapping("/preferences/signals")
    public Result<List<Map<String, Object>>> preferenceSignalList() {
        return Result.ok(itineraryService.preferenceSignals(currentUserId(), 50));
    }

    @GetMapping("/{id}/versions")
    public Result<List<Map<String, Object>>> versions(@PathVariable Long id) {
        return Result.ok(itineraryService.listVersions(currentUserId(), id));
    }

    @GetMapping("/{id}/versions/diff")
    public Result<Map<String, Object>> versionDiff(@PathVariable Long id,
                                                   @org.springframework.web.bind.annotation.RequestParam Long fromVersionId,
                                                   @org.springframework.web.bind.annotation.RequestParam Long toVersionId) {
        return Result.ok(itineraryService.diffVersions(currentUserId(), id, fromVersionId, toVersionId));
    }

    @PostMapping("/{id}/versions")
    public Result<Map<String, Object>> createVersion(@PathVariable Long id,
                                                     @RequestBody Map<String, String> body) {
        return Result.ok(itineraryService.createVersion(currentUserId(), id,
                body.getOrDefault("operation", "snapshot"), body.getOrDefault("summary", "行程快照")));
    }

    @PostMapping("/{id}/versions/{versionId}/restore")
    public Result<ItineraryVO> restoreVersion(@PathVariable Long id, @PathVariable Long versionId) {
        return Result.ok(itineraryService.restoreVersion(currentUserId(), id, versionId));
    }

    /**
     * 获取当前登录用户 ID（从 JWT 中解析）。
     * J9：包一层请求内记忆化——一个请求多次调用 currentUserId 只 getByUsername 查一次库。
     */
    private Long currentUserId() {
        return SecurityUtils.cachedUserId(() ->
                userService.getByUsername(SecurityUtils.currentUsername()).getId());
    }
}
