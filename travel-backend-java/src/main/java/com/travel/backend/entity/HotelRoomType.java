package com.travel.backend.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.math.BigDecimal;

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
