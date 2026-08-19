package com.travel.backend.service;

import com.travel.backend.dto.LoginRequest;
import com.travel.backend.dto.RegisterRequest;
import com.travel.backend.vo.LoginResponse;
import com.travel.backend.vo.UserVO;

public interface UserService {

    UserVO register(RegisterRequest request);

    LoginResponse login(LoginRequest request);

    UserVO getByUsername(String username);
}