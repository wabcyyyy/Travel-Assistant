package com.travel.backend.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.travel.backend.entity.CityConsumption;
import org.apache.ibatis.annotations.Mapper;

/**
 * 城市消费系数表 Mapper 接口。
 *
 * @see com.travel.backend.entity.CityConsumption
 */
@Mapper
public interface CityConsumptionMapper extends BaseMapper<CityConsumption> {
}