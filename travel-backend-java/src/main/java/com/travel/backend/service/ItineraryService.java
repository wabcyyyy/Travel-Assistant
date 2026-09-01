package com.travel.backend.service;

import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.dto.HotelOptionApplyRequest;
import com.travel.backend.dto.ItemUpsertRequest;
import com.travel.backend.vo.ItinerarySummaryVO;
import com.travel.backend.vo.ItineraryVO;

import java.util.List;
import java.util.Map;

/**
 * 行程管理核心业务接口。
 *
 * <p>提供行程的完整生命周期管理，包括：</p>
 * <ul>
 *   <li>CRUD：生成、列表、详情、删除</li>
 *   <li>行程项管理：新增、更新、删除、拖拽排序</li>
 *   <li>对话编辑：自然语言修改行程、槽位澄清</li>
 *   <li>草稿应用：确认应用对话编辑产生的草稿方案</li>
 *   <li>偏好管理：用户偏好统计与推荐</li>
 * </ul>
 *
 * <p>所有写操作均通过 {@link com.travel.backend.common.BizException} 抛出业务异常。</p>
 *
 * @see com.travel.backend.serviceImpl.ItineraryServiceImpl
 */
public interface ItineraryService {

    /** 生成行程：建壳 → 异步逐日生成 → 返回初始状态（status=1）。 */
    ItineraryVO generate(Long userId, GenerateRequest request);

    /** 查询用户行程列表（按创建时间倒序）。 */
    List<ItinerarySummaryVO> list(Long userId);

    /** 查询行程详情（含日行程 + 行程项 + 预算）。 */
    ItineraryVO detail(Long userId, Long id);

    /** 删除行程（逻辑删除）。 */
    void delete(Long userId, Long id);

    /** 新增行程项（景点/餐饮/酒店/交通）。 */
    ItineraryVO addItem(Long userId, Long itineraryId, ItemUpsertRequest request);

    /** 更新行程项（时间/费用/标签等）。 */
    ItineraryVO updateItem(Long userId, Long itemId, ItemUpsertRequest request);

    /** 删除行程项。 */
    ItineraryVO deleteItem(Long userId, Long itemId);

    /** 拖拽排序：指定日内行程项的顺序。 */
    ItineraryVO reorderItems(Long userId, Long itineraryId, Long dayId, List<Long> itemIds);

    /** 自然语言编辑：解析指令并执行操作（删除/新增/移动等）。 */
    Map<String, Object> nlEdit(Long userId, Long itineraryId, String instruction);

    /** 槽位澄清：从用户输入中抽取行程参数，返回缺失字段和追问。 */
    Map<String, Object> clarify(String message, Map<String, Object> slots);

    /** 对话编辑：基于当前行程 + 用户消息，返回草稿方案（不落库）。 */
    Map<String, Object> chatEdit(Long userId, Long itineraryId, String message,
                                 List<Map<String, Object>> history);

    /** 获取对话历史（按时间正序）。 */
    List<Map<String, Object>> chatHistory(Long userId, Long itineraryId);

    /** 清空对话历史。 */
    void clearChatHistory(Long userId, Long itineraryId);

    /** 应用草稿方案：校验版本一致性 → 事务内逐项落库。 */
    ItineraryVO applyPlans(Long userId, Long itineraryId, List<Map<String, Object>> plans,
                           Long actionMessageId, String baseRevision);

    /** 应用酒店选项：校验房型价格 → 按季节因子调整 → 逐晚插入/更新。 */
    ItineraryVO applyHotelOption(Long userId, Long itineraryId, HotelOptionApplyRequest request);

    /** 获取支持的目的地城市列表。 */
    List<String> supportedCities();

    /** 城市引导对话：用户不确定去哪时，AI 根据偏好推荐城市。 */
    Map<String, Object> cityGuide(String input, List<Map<String, Object>> history);

    /** 获取用户偏好 top N（按选择次数降序）。 */
    List<String> topPreferences(Long userId, int limit);

    /** 记录用户偏好选择（有则 +1，无则插入）。 */
    void recordPreferences(Long userId, List<String> preferences);
}
