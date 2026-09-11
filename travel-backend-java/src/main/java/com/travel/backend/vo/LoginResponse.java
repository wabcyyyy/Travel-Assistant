package com.travel.backend.vo;

import lombok.Data;

/**
 * 登录响应。凭据在 HttpOnly Cookie（TA_AUTH），body 默认不携带 JWT，
 * 避免前端 localStorage/内存 XSS 面；脚本联调可用 Cookie 或后续加一次性登录码。
 */
@Data
public class LoginResponse {

    /** @deprecated 仅兼容字段；浏览器主凭据为 HttpOnly Cookie，此字段恒为 null。 */
    private String token;
    private UserVO user;

    public LoginResponse() {
    }

    public LoginResponse(UserVO user) {
        this.token = null;
        this.user = user;
    }

    /** 兼容旧构造：忽略 token，不再回传到客户端。 */
    public LoginResponse(String token, UserVO user) {
        this.token = null;
        this.user = user;
    }
}
