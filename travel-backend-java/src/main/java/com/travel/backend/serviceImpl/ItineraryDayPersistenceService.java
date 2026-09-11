package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.travel.backend.common.BizException;
import com.travel.backend.dto.AgentGenerateResponse;
import com.travel.backend.dto.GenerateRequest;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.service.BudgetEngine;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalTime;
import java.util.LinkedHashMap;
import java.util.Map;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * 每日结果的事务写入与幂等保护。
 *
 * <p>远程 Agent 调用发生在事务外；只有完整结果准备好后才在一个短事务中
 * 清理旧草稿、写入全部项目并标记 SUCCEEDED，避免响应丢失或半写入造成重复。</p>
 */
@Service
public class ItineraryDayPersistenceService {

    private final ItineraryDayMapper dayMapper;
    private final ItineraryItemMapper itemMapper;
    private final BudgetEngine budgetEngine;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public ItineraryDayPersistenceService(ItineraryDayMapper dayMapper,
                                          ItineraryItemMapper itemMapper,
                                          BudgetEngine budgetEngine) {
        this.dayMapper = dayMapper;
        this.itemMapper = itemMapper;
        this.budgetEngine = budgetEngine;
    }

    @Transactional
    public void persist(Long itineraryId, GenerateRequest request, int dayNo,
                        AgentGenerateResponse.DailyPlan plan,
                        String actionId, String fingerprint) {
        ItineraryDay day = dayMapper.selectOne(new LambdaQueryWrapper<ItineraryDay>()
                .eq(ItineraryDay::getItineraryId, itineraryId)
                .eq(ItineraryDay::getDayNo, dayNo));
        if (day == null) {
            throw new BizException(500, "行程日不存在");
        }
        verifyAction(day, actionId, fingerprint);
        if ("SUCCEEDED".equals(day.getGenerationStatus())) {
            return;
        }

        day.setGenerationActionId(actionId);
        day.setGenerationFingerprint(fingerprint);
        day.setGenerationStatus("RUNNING");
        day.setGenerationError(null);
        if (plan.getNote() != null) {
            day.setNote(plan.getNote());
        }
        Map<String, Object> metadata = new LinkedHashMap<>();
        if (plan.getTheme() != null) metadata.put("theme", plan.getTheme());
        if (plan.getMiniRoute() != null && !plan.getMiniRoute().isEmpty()) metadata.put("miniRoute", plan.getMiniRoute());
        if (plan.getBackupPlan() != null && !plan.getBackupPlan().isEmpty()) metadata.put("backupPlan", plan.getBackupPlan());
        if (plan.getPhotoSpots() != null && !plan.getPhotoSpots().isEmpty()) metadata.put("photoSpots", plan.getPhotoSpots());
        if (plan.getPracticalNotes() != null && !plan.getPracticalNotes().isEmpty()) metadata.put("practicalNotes", plan.getPracticalNotes());
        try {
            day.setMetadataJson(metadata.isEmpty() ? null : objectMapper.writeValueAsString(metadata));
        } catch (Exception ignored) {
            day.setMetadataJson(null);
        }
        dayMapper.updateById(day);

        // 失败重试或恢复时清理可能遗留的半成品；本方法处于事务中，失败会整体回滚。
        itemMapper.delete(new LambdaQueryWrapper<ItineraryItem>().eq(ItineraryItem::getDayId, day.getId()));
        int sortNo = 0;
        int stayNights = request.getStayNights() == null
                ? Math.max(request.getDays() - 1, 0) : request.getStayNights();
        if (plan.getItems() != null) {
            for (AgentGenerateResponse.Item item : plan.getItems()) {
                if ("hotel".equals(item.getItemType()) && dayNo > stayNights) {
                    continue;
                }
                ItineraryItem entity = new ItineraryItem();
                entity.setDayId(day.getId());
                entity.setItineraryId(itineraryId);
                entity.setItemType(item.getItemType());
                entity.setPoiName(item.getPoiName());
                entity.setPoiId(item.getPoiId());
                entity.setAddress(item.getAddress());
                entity.setLatitude(item.getLatitude());
                entity.setLongitude(item.getLongitude());
                entity.setStartTime(parseTimeSafe(item.getStartTime()));
                entity.setEndTime(parseTimeSafe(item.getEndTime()));
                entity.setDurationMin(item.getDurationMin());
                entity.setCost(item.getCost());
                entity.setTag(item.getTag());
                entity.setRemark(item.getRemark());
                entity.setOpenTime(item.getOpenTime());
                entity.setImageUrl(item.getImage());
                entity.setSource(item.getSource());
                entity.setSourceUpdatedAt(parseDateTimeSafe(item.getSourceUpdatedAt()));
                entity.setVerificationStatus(defaultString(item.getVerificationStatus(), "unverified"));
                entity.setValueKind(defaultString(item.getValueKind(), "generated"));
                entity.setFreshnessStatus(defaultString(item.getFreshnessStatus(), "unknown"));
                entity.setReviewRequirement(defaultString(item.getReviewRequirement(), "before_departure"));
                if (item.getFactEvidence() != null && !item.getFactEvidence().isEmpty()) {
                    try {
                        entity.setFactEvidenceJson(objectMapper.writeValueAsString(item.getFactEvidence()));
                    } catch (Exception ignored) {
                        entity.setFactEvidenceJson(null);
                    }
                }
                entity.setSortNo(sortNo++);
                itemMapper.insert(entity);
            }
        }
        day.setGenerationStatus("SUCCEEDED");
        day.setGenerationError(null);
        dayMapper.updateById(day);
        budgetEngine.recalculate(itineraryId);
    }

    @Transactional
    public void markRunning(ItineraryDay day, String actionId, String fingerprint) {
        verifyAction(day, actionId, fingerprint);
        day.setGenerationActionId(actionId);
        day.setGenerationFingerprint(fingerprint);
        day.setGenerationStatus("RUNNING");
        day.setGenerationError(null);
        dayMapper.updateById(day);
    }

    @Transactional
    public void markFailed(ItineraryDay day, String actionId, String fingerprint, String error) {
        verifyAction(day, actionId, fingerprint);
        day.setGenerationActionId(actionId);
        day.setGenerationFingerprint(fingerprint);
        day.setGenerationStatus("FAILED");
        day.setGenerationError(error == null ? "每日生成失败" : error.substring(0, Math.min(error.length(), 500)));
        dayMapper.updateById(day);
    }

    private void verifyAction(ItineraryDay day, String actionId, String fingerprint) {
        if (day.getGenerationActionId() != null && !day.getGenerationActionId().equals(actionId)) {
            throw new BizException(409, "该日期已有不同的生成动作，请使用最新任务");
        }
        if (day.getGenerationFingerprint() != null && !day.getGenerationFingerprint().equals(fingerprint)) {
            throw new BizException(409, "同一日期生成参数已发生变化，请重新创建行程");
        }
    }

    private LocalTime parseTimeSafe(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String normalized = value.trim();
        if (normalized.startsWith("24:")) {
            normalized = "00:" + normalized.substring(3);
        }
        try {
            return LocalTime.parse(normalized);
        } catch (Exception ignored) {
            return null;
        }
    }

    private java.time.LocalDateTime parseDateTimeSafe(String value) {
        if (value == null || value.isBlank()) return null;
        try {
            return java.time.OffsetDateTime.parse(value).toLocalDateTime();
        } catch (Exception ignored) {
            try {
                return java.time.LocalDateTime.parse(value);
            } catch (Exception ignoredAgain) {
                return null;
            }
        }
    }

    private String defaultString(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value;
    }
}
