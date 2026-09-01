package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.travel.backend.entity.UserPreference;
import com.travel.backend.mapper.UserPreferenceMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

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
                                .last("LIMIT " + safeLimit))
                .stream()
                .map(UserPreference::getPrefLabel)
                .toList();
    }

    @Transactional
    public void recordPreferences(Long userId, List<String> preferences) {
        if (preferences == null || preferences.isEmpty()) {
            return;
        }
        for (String label : preferences) {
            if (label == null || label.isBlank()) {
                continue;
            }
            UserPreference existing = userPreferenceMapper.selectOne(
                    new LambdaQueryWrapper<UserPreference>()
                            .eq(UserPreference::getUserId, userId)
                            .eq(UserPreference::getPrefLabel, label));
            if (existing != null) {
                existing.setCount(existing.getCount() + 1);
                userPreferenceMapper.updateById(existing);
            } else {
                UserPreference preference = new UserPreference();
                preference.setUserId(userId);
                preference.setPrefLabel(label);
                preference.setCount(1);
                userPreferenceMapper.insert(preference);
            }
        }
    }
}
