package com.travel.backend;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;

@SpringBootApplication
@EnableAsync
@MapperScan("com.travel.backend.mapper")
public class TravelBackendApplication {

    public static void main(String[] args) {
        SpringApplication.run(TravelBackendApplication.class, args);
    }
}