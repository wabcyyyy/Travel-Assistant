package com.travel.backend.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class RegisterRequest {

    @NotBlank(message = "用户名不能为空")
    @Size(min = 3, max = 32, message = "用户名长度需在 3-32 之间")
    @Pattern(regexp = "^[A-Za-z0-9_\\u4e00-\\u9fa5]+$", message = "用户名仅支持中英文、数字与下划线")
    private String username;

    /**
     * 密码：8-32 位，至少包含字母与数字两类，降低弱口令撞库成功率。
     */
    @NotBlank(message = "密码不能为空")
    @Size(min = 8, max = 32, message = "密码长度需在 8-32 之间")
    @Pattern(regexp = "^[A-Za-z0-9!@#$%^&*_-]+$", message = "密码包含非法字符")
    private String password;

    @Size(max = 32, message = "昵称长度需在 32 以内")
    private String nickname;
}
