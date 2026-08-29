package com.travel.backend.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.travel.backend.entity.UserPreference;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface UserPreferenceMapper extends BaseMapper<UserPreference> {
}
