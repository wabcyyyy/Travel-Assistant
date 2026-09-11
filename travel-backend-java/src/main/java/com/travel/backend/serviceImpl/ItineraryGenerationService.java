package com.travel.backend.serviceImpl;

import com.fasterxml.jackson.databind.JsonNode;
import com.travel.backend.common.BizException;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import com.travel.backend.service.AgentService;
import com.travel.backend.vo.ItineraryVO;
import org.springframework.cache.annotation.CacheEvict;
import org.springframework.stereotype.Service;

import java.time.temporal.ChronoUnit;

/** 创建行程壳数据并启动逐日异步生成。 */
@Service
public class ItineraryGenerationService {

    private final ItineraryMainMapper mainMapper;
    private final ItineraryDayMapper dayMapper;
    private final AgentService agentService;
    private final ItineraryAsyncPlanner planner;
    private final ItineraryQueryService queryService;
    private final UserPreferenceService preferenceService;
    private final ItineraryVersionService versionService;

    public ItineraryGenerationService(ItineraryMainMapper mainMapper, ItineraryDayMapper dayMapper,
                                      AgentService agentService, ItineraryAsyncPlanner planner,
                                      ItineraryQueryService queryService,
                                      UserPreferenceService preferenceService,
                                      ItineraryVersionService versionService) {
        this.mainMapper = mainMapper;
        this.dayMapper = dayMapper;
        this.agentService = agentService;
        this.planner = planner;
        this.queryService = queryService;
        this.preferenceService = preferenceService;
        this.versionService = versionService;
    }

    @CacheEvict(cacheNames = "itinerary:detail", allEntries = true)
    public ItineraryVO generate(Long userId, GenerateRequest request) {
        validateRequest(request);
        int stayNights = request.getStayNights() == null
                ? Math.max(request.getDays() - 1, 0) : request.getStayNights();
        if (stayNights < 0 || stayNights > request.getDays()) {
            throw new BizException(400, "住宿晚数必须在 0 到行程天数之间");
        }
        request.setStayNights(stayNights);

        // 先提交可查询的壳数据，再启动异步逐日规划，避免异步线程读不到未提交数据。
        ItineraryMain main = new ItineraryMain();
        main.setUserId(userId);
        main.setTitle(request.getCity() + request.getDays() + "日游");
        main.setCity(request.getCity());
        main.setStartDate(request.getStartDate());
        main.setEndDate(request.getEndDate());
        main.setDays(request.getDays());
        main.setPersons(request.getPersons());
        main.setBudget(request.getBudget());
        main.setPreferences(request.getPreferences() == null ? null : String.join(",", request.getPreferences()));
        main.setHotelTier(request.getHotelTier());
        main.setStayNights(stayNights);
        main.setStatus(1);
        mainMapper.insert(main);

        for (int dayNo = 1; dayNo <= request.getDays(); dayNo++) {
            ItineraryDay day = new ItineraryDay();
            day.setItineraryId(main.getId());
            day.setDayNo(dayNo);
            day.setCity(request.getCity());
            day.setTravelDate(request.getStartDate() == null ? null
                    : request.getStartDate().plusDays(dayNo - 1L));
            day.setGenerationStatus("PENDING");
            dayMapper.insert(day);
        }

        preferenceService.recordPreferences(userId, request.getPreferences());
        versionService.createSnapshot(userId, main.getId(), "create", "创建行程草稿");
        // 上下文检索包含知识库/RAG/高德网络请求，不能阻塞创建接口。
        // 先返回可轮询的行程壳数据，再由异步规划线程构建一次上下文并逐日生成。
        try {
            planner.planDays(userId, main.getId(), request, null);
        } catch (org.springframework.core.task.TaskRejectedException rejected) {
            // H6：生成专用池已满，快速失败返回 429；不能回退到请求线程同步生成。
            // 壳数据置为失败终态，用户可见并可重新创建（该状态不满足自动续跑条件）。
            main.setStatus(3);
            main.setPlanNote("生成失败：系统繁忙，生成队列已满");
            mainMapper.updateById(main);
            throw new BizException(429, "行程生成任务已满，系统繁忙，请稍后再试");
        }
        return queryService.detail(userId, main.getId());
    }

    private static final java.util.regex.Pattern CITY_PATTERN =
            java.util.regex.Pattern.compile("^[\\p{IsHan}A-Za-z0-9][\\p{IsHan}A-Za-z0-9\\s·'’\\-()（）]{0,30}$");

    private void validateRequest(GenerateRequest request) {
        if (request == null || request.getCity() == null || request.getCity().isBlank()) {
            throw new BizException(400, "目的地不能为空");
        }
        String city = request.getCity().trim();
        if (city.length() > 32 || !CITY_PATTERN.matcher(city).matches()) {
            throw new BizException(400, "目的地名称格式不正确，请输入城市或景点所在城市");
        }
        request.setCity(city);
        if (request.getDays() == null || request.getDays() < 1
                || request.getDays() > GenerateRequest.MAX_TRIP_DAYS) {
            throw new BizException(400, "每次生成行程不能超过 7 天");
        }
        if (request.getPersons() == null || request.getPersons() < 1 || request.getPersons() > 20) {
            throw new BizException(400, "出行人数必须在 1 到 20 人之间");
        }
        if (request.getStartDate() != null && request.getEndDate() != null) {
            if (request.getEndDate().isBefore(request.getStartDate())) {
                throw new BizException(400, "结束日期不能早于开始日期");
            }
            long dateDays = ChronoUnit.DAYS.between(request.getStartDate(), request.getEndDate()) + 1;
            if (dateDays != request.getDays()) {
                throw new BizException(400, "日期范围与行程天数不一致");
            }
        }
    }
}
