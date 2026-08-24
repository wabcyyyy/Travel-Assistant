package com.travel.backend.controller;

import com.travel.backend.common.Result;
import com.travel.backend.service.AmapService;
import com.travel.backend.vo.AmapGeocodeVO;
import com.travel.backend.vo.AmapPoiVO;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestTemplate;

import java.net.URI;
import java.util.List;

@RestController
@RequestMapping("/api/amap")
public class AmapController {

    private final AmapService amapService;
    private final RestTemplate restTemplate;

    @Value("${app.amap.web-key:}")
    private String amapKey;

    public AmapController(AmapService amapService, RestTemplate restTemplate) {
        this.amapService = amapService;
        this.restTemplate = restTemplate;
    }

    /** 高德静态地图代理：供行程卡片展示点位缩略图（只读，免鉴权）。 */
    @GetMapping("/staticmap")
    public ResponseEntity<byte[]> staticmap(@RequestParam String location) {
        String url = "https://restapi.amap.com/v3/staticmap?location=" + location
                + "&zoom=16&size=480*280&key=" + amapKey;
        byte[] image = restTemplate.getForObject(URI.create(url), byte[].class);
        return ResponseEntity.ok().contentType(MediaType.IMAGE_JPEG).body(image);
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