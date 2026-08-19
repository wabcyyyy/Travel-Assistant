package com.travel.backend.controller;

import com.travel.backend.common.Result;
import com.travel.backend.service.AmapService;
import com.travel.backend.vo.AmapGeocodeVO;
import com.travel.backend.vo.AmapPoiVO;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/amap")
public class AmapController {

    private final AmapService amapService;

    public AmapController(AmapService amapService) {
        this.amapService = amapService;
    }

    @GetMapping("/geocode")
    public Result<List<AmapGeocodeVO>> geocode(@RequestParam String address,
                                               @RequestParam(required = false) String city) {
        return Result.ok(amapService.geocode(address, city));
    }

    @GetMapping("/poi")
    public Result<List<AmapPoiVO>> searchPoi(@RequestParam String keywords,
                                             @RequestParam(required = false) String city,
                                             @RequestParam(required = false) String types) {
        return Result.ok(amapService.searchPoi(keywords, city, types));
    }
}