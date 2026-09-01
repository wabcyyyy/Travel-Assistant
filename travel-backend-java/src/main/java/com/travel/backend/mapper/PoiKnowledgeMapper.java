package com.travel.backend.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.travel.backend.entity.PoiKnowledge;
import org.apache.ibatis.annotations.Mapper;

/**
 * 景点知识库 Mapper 接口。
 *
 * @see com.travel.backend.entity.PoiKnowledge
 */
@Mapper
public interface PoiKnowledgeMapper extends BaseMapper<PoiKnowledge> {
}