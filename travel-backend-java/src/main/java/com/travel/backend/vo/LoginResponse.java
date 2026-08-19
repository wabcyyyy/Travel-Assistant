package com.travel.backend.vo;

import lombok.Data;

@Data
public class LoginResponse {

    private String token;
    private UserVO user;

    public LoginResponse() {
    }

    public LoginResponse(String token, UserVO user) {
        this.token = token;
        this.user = user;
    }
}