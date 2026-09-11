package com.travel.backend.service;

import com.travel.backend.dto.LoginRequest;
import com.travel.backend.dto.RegisterRequest;
import com.travel.backend.vo.LoginResponse;
import com.travel.backend.vo.UserVO;

public interface UserService {

    UserVO register(RegisterRequest request);

    LoginResponse login(LoginRequest request);

    /**
     * 服务端吊销当前 Bearer/Cookie Token（logout）。Token 无效/过期时静默成功。
     */
    void logout(String rawToken);

    /**
     * 吊销该用户全部已登记会话（多端登出）。返回吊销条数。
     */
    int logoutAll(String username);

    UserVO getByUsername(String username);
}
