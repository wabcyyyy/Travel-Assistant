package com.travel.backend.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.travel.backend.entity.ItineraryChatMessage;
import org.apache.ibatis.annotations.Mapper;

/**
 * 行程对话记忆表 Mapper 接口。
 *
 * @see com.travel.backend.entity.ItineraryChatMessage
 */
@Mapper
public interface ItineraryChatMessageMapper extends BaseMapper<ItineraryChatMessage> {
}
