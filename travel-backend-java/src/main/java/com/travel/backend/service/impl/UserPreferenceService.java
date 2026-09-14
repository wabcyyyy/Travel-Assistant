package com.travel.backend.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.travel.backend.entity.UserPreference;
import com.travel.backend.mapper.UserPreferenceMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Map;

/** 用户偏好记录与高频偏好查询。 */
@Service
public class UserPreferenceService {

    private final UserPreferenceMapper userPreferenceMapper;

    public UserPreferenceService(UserPreferenceMapper userPreferenceMapper) {
        this.userPreferenceMapper = userPreferenceMapper;
    }

    public List<String> topPreferences(Long userId, int limit) {
        int safeLimit = Math.max(1, Math.min(limit, 20));
        return userPreferenceMapper.selectList(
                new LambdaQueryWrapper<UserPreference>()
                        .eq(UserPreference::getUserId, userId)
                        .orderByDesc(UserPreference::getCount)
                        .eq(UserPreference::getNegative, 0)
                        .last("LIMIT " + safeLimit))
                .stream()
                .map(UserPreference::getPrefLabel)
                .toList();
    }

    @Transactional
    public void recordPreferences(Long userId, List<String> preferences) {
        recordSignals(userId, preferences, List.of(), List.of(), "explicit", 1.0);
    }

    @Transactional
    public void recordSignals(Long userId, List<String> explicit, List<String> hard,
                              List<String> negative, String source, double confidence) {
        recordOne(userId, explicit, source, confidence, false, false);
        recordOne(userId, hard, source, confidence, false, true);
        recordOne(userId, negative, source, confidence, true, false);
    }

    public List<Map<String, Object>> signals(Long userId, int limit) {
        int safeLimit = Math.max(1, Math.min(limit, 50));
        return userPreferenceMapper.selectList(new LambdaQueryWrapper<UserPreference>()
                        .eq(UserPreference::getUserId, userId)
                        .orderByDesc(UserPreference::getHardConstraint)
                        .orderByDesc(UserPreference::getUpdatedAt)
                        .last("LIMIT " + safeLimit))
                .stream().map(item -> {
                    Map<String, Object> result = new LinkedHashMap<>();
                    result.put("label", item.getPrefLabel());
                    result.put("count", item.getCount());
                    result.put("source", item.getSource());
                    result.put("confidence", item.getConfidence());
                    result.put("negative", Integer.valueOf(1).equals(item.getNegative()));
                    result.put("hardConstraint", Integer.valueOf(1).equals(item.getHardConstraint()));
                    result.put("lastSeenAt", item.getLastSeenAt());
                    return result;
                }).toList();
    }

    private void recordOne(Long userId, List<String> labels, String source, double confidence,
                           boolean negative, boolean hardConstraint) {
        if (labels == null) return;
        for (String label : labels) {
            if (label == null || label.isBlank()) continue;
            UserPreference existing = userPreferenceMapper.selectOne(new LambdaQueryWrapper<UserPreference>()
                    .eq(UserPreference::getUserId, userId)
                    .eq(UserPreference::getPrefLabel, label.trim()));
            if (existing == null) {
                existing = new UserPreference();
                existing.setUserId(userId);
                existing.setPrefLabel(label.trim());
                existing.setCount(negative ? 0 : 1);
                existing.setNegative(negative ? 1 : 0);
                existing.setHardConstraint(hardConstraint ? 1 : 0);
            } else if (!negative) {
                existing.setCount((existing.getCount() == null ? 0 : existing.getCount()) + 1);
            }
            // user_preference 的唯一键是 (user_id, pref_label)：正向、负向和硬约束信号
            // 共用同一条记录，避免同一标签因 negative 不同而重复插入。
            existing.setNegative(negative ? 1 : 0);
            existing.setHardConstraint(hardConstraint || Integer.valueOf(1).equals(existing.getHardConstraint()) ? 1 : 0);
            existing.setSource(source == null || source.isBlank() ? "explicit" : source);
            existing.setConfidence(java.math.BigDecimal.valueOf(Math.max(0, Math.min(1, confidence))));
            existing.setLastSeenAt(java.time.LocalDateTime.now());
            if (existing.getId() == null) userPreferenceMapper.insert(existing);
            else userPreferenceMapper.updateById(existing);
        }
    }
}
