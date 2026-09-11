package com.travel.backend.vo;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * 后台管理-用户列表条目。
 */
@Data
public class AdminUserVO {

    private Long id;
    private String username;
    private String nickname;
    private String phone;
    /** 状态 1-正常 0-禁用 */
    private Integer status;
    /** 角色 user-普通用户 admin-管理员 */
    private String role;
    /** 该用户行程数（含各状态，不含已删除） */
    private Long itineraryCount;
    private LocalDateTime createdAt;
}
