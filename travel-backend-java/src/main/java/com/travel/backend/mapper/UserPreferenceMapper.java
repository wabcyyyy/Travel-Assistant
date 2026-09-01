package com.travel.backend.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.travel.backend.entity.UserPreference;
import org.apache.ibatis.annotations.Mapper;

/**
 * 用户偏好统计表 Mapper 接口。
 *
 * @see com.travel.backend.entity.UserPreference
 */
@Mapper
public interface UserPreferenceMapper extends BaseMapper<UserPreference> {
}
