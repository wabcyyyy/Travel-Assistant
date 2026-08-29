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

    @Value("${app.unsplash.access-key:}")
    private String unsplashAccessKey;

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

    /** POI 实景照片：优先 Unsplash 真实摄影图，回退高德（过滤地图位置图）；302 跳转，无图返回 404（前端降级静态图）。 */
    @GetMapping("/poi-photo")
    public ResponseEntity<Void> poiPhoto(@RequestParam String name, @RequestParam String city) {
        String cacheKey = city + ":" + name;
        String photoUrl = photoCache.get(cacheKey);
        if (photoUrl == null) {
            try {
                photoUrl = unsplashPhoto(name, city);
            } catch (Exception e) {
                photoUrl = null;
            }
            if (photoUrl == null || photoUrl.isBlank()) {
                try {
                    String url = "https://restapi.amap.com/v3/place/text?keywords=" + name
                            + "&city=" + city + "&citylimit=true&offset=1&page=1&key=" + amapKey;
                    ResponseEntity<String> resp =
                            restTemplate.getForEntity(URI.create(url), String.class);
                    JsonNode poi = objectMapper.readTree(resp.getBody())
                            .path("pois").path(0);
                    JsonNode photos = poi.path("photos");
                    if (photos.isArray()) {
                        for (JsonNode photo : photos) {
                            String title = photo.path("title").asText("");
                            String candidate = photo.path("url").asText(null);
                            if (candidate != null && !candidate.isBlank()
                                    && !title.contains("地图") && !title.contains("位置")) {
                                photoUrl = candidate;
                                break;
                            }
                        }
                    }
                } catch (Exception e) {
                    photoUrl = "";
                }
            }
            photoCache.put(cacheKey, photoUrl == null ? "" : photoUrl);
        }
        if (photoUrl == null || photoUrl.isBlank()) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.status(302).location(URI.create(photoUrl)).build();
    }

    /** Unsplash 检索 POI 实景图；未配置 access key 或请求失败时返回 null。 */
    private String unsplashPhoto(String name, String city) {
        if (unsplashAccessKey == null || unsplashAccessKey.isBlank()) {
            return null;
        }
        try {
            String query = java.net.URLEncoder.encode(
                    (name + " " + (city == null ? "" : city)).trim(),
                    java.nio.charset.StandardCharsets.UTF_8);
            String url = "https://api.unsplash.com/search/photos?query=" + query
                    + "&per_page=1&orientation=landscape&client_id=" + unsplashAccessKey;
            ResponseEntity<String> resp = restTemplate.getForEntity(URI.create(url), String.class);
            JsonNode urls = objectMapper.readTree(resp.getBody())
                    .path("results").path(0).path("urls");
            String regular = urls.path("regular").asText(null);
            return regular == null || regular.isBlank() ? null : regular;
        } catch (Exception e) {
            return null;
        }
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