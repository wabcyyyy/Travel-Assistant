package com.travel.backend.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
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
import java.util.Map;

@RestController
@RequestMapping("/api/amap")
public class AmapController {

    private final AmapService amapService;
    private final RestTemplate restTemplate;
    private final ObjectMapper objectMapper = new ObjectMapper();

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

    private final Map<String, String> photoCache = new java.util.concurrent.ConcurrentHashMap<>();

    /** 高德 POI 实景照片：302 跳转到真实图片 URL；无图返回 404（前端降级静态图）。 */
    @GetMapping("/poi-photo")
    public ResponseEntity<Void> poiPhoto(@RequestParam String name, @RequestParam String city) {
        String cacheKey = city + ":" + name;
        String photoUrl = photoCache.get(cacheKey);
        if (photoUrl == null) {
            try {
                String url = "https://restapi.amap.com/v3/place/text?keywords=" + name
                        + "&city=" + city + "&citylimit=true&offset=1&page=1&key=" + amapKey;
                ResponseEntity<String> resp =
                        restTemplate.getForEntity(URI.create(url), String.class);
                JsonNode poi = objectMapper.readTree(resp.getBody())
                        .path("pois").path(0);
                JsonNode photos = poi.path("photos");
                if (photos.isArray() && photos.size() > 0) {
                    photoUrl = photos.get(0).path("url").asText(null);
                }
            } catch (Exception e) {
                photoUrl = "";
            }
            photoCache.put(cacheKey, photoUrl == null ? "" : photoUrl);
        }
        if (photoUrl == null || photoUrl.isBlank()) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.status(302).location(URI.create(photoUrl)).build();
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