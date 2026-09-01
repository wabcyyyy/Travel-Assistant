package com.travel.backend.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.travel.backend.entity.ItineraryMain;

/**
 * 行程主表 Mapper 接口。
 *
 * <p>继承 MyBatis-Plus {@link BaseMapper}，提供基本的 CRUD 操作。
 * 复杂查询通过 {@link com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper} 构建。</p>
 *
 * @see com.travel.backend.entity.ItineraryMain
 */
public interface ItineraryMainMapper extends BaseMapper<ItineraryMain> {
}