package com.travel.backend.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.travel.backend.entity.HotelRoomType;
import org.apache.ibatis.annotations.Mapper;

/**
 * 酒店房型表 Mapper 接口。
 *
 * @see com.travel.backend.entity.HotelRoomType
 */
@Mapper
public interface HotelRoomTypeMapper extends BaseMapper<HotelRoomType> {
}
