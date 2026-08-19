package com.travel.backend.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class RegisterRequest {

    @NotBlank(message = "用户名不能为空")
    @Size(min = 3, max = 32, message = "用户名长度需在 3-32 之间")
    private String username;

    @NotBlank(message = "密码不能为空")
    @Size(min = 6, max = 32, message = "密码长度需在 6-32 之间")
    @Pattern(regexp = "^[\\w!@#$%^&*]+$", message = "密码包含非法字符")
    private String password;

    @Size(max = 32, message = "昵称长度需在 32 以内")
    private String nickname;
}