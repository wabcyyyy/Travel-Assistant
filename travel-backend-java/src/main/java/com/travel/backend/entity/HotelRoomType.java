package com.travel.backend.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;

/**
 * 酒店房型表实体。
 *
 * <p>对应表 {@code hotel_room_type}，存储酒店的房型信息和参考价格。</p>
 *
 * <p>在对话编辑的酒店候选确认流程中使用：
 * 用户选择酒店后，展示可选房型（标准间/大床房/套房等），
 * 价格按季节因子调整后计算总价。</p>
 *
 * @see PoiKnowledge
 */
@Data
@TableName("hotel_room_type")
public class HotelRoomType {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long poiId;
    private String roomName;
    private BigDecimal basePrice;
    private Integer capacity;
    private String bedType;
    private String breakfast;
    private String description;
    private Integer isDefault;
}
