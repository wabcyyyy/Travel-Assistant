package com.travel.backend.controller;

import com.travel.backend.common.Result;
import com.travel.backend.service.AmapService;
import com.travel.backend.service.impl.AmapImageProxyService;
import com.travel.backend.service.impl.AmapPhotoService;
import com.travel.backend.vo.AmapGeocodeVO;
import com.travel.backend.vo.AmapPoiVO;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClient;
import org.springframework.web.util.UriComponentsBuilder;

import java.net.URI;
import java.util.List;

@RestController
@RequestMapping("/api/amap")
public class AmapController {

    private final AmapService amapService;
    private final RestClient imageRestClient;
    private final AmapImageProxyService amapImageProxyService;
    private final AmapPhotoService amapPhotoService;

    @Value("${app.amap.web-key:}")
    private String amapKey;

    public AmapController(AmapService amapService, RestClient imageRestClient,
                          AmapImageProxyService amapImageProxyService,
                          AmapPhotoService amapPhotoService) {
        this.amapService = amapService;
        this.imageRestClient = imageRestClient;
        this.amapImageProxyService = amapImageProxyService;
        this.amapPhotoService = amapPhotoService;
    }

    /** 高德静态地图代理：供行程卡片展示点位缩略图（只读，免鉴权）。 */
    @GetMapping("/staticmap")
    public ResponseEntity<byte[]> staticmap(@RequestParam String location) {
        // location 必须是 "lng,lat" 数字格式：匿名端点直接拼 URL 会被注入
        // "&" 覆盖后续参数（如替换 key），必须校验 + 编码构建。
        if (!isLngLat(location)) {
            return ResponseEntity.badRequest().build();
        }
        URI uri = UriComponentsBuilder.fromUriString("https://restapi.amap.com/v3/staticmap")
                .queryParam("location", location)
                .queryParam("zoom", 16)
                .queryParam("size", "480*280")
                .queryParam("key", amapKey)
                .build().encode().toUri();
        try {
            byte[] image = imageRestClient.get().uri(uri).retrieve().body(byte[].class);
            if (image == null || image.length == 0) return ResponseEntity.notFound().build();
            return ResponseEntity.ok().contentType(MediaType.IMAGE_JPEG)
                    .cacheControl(org.springframework.http.CacheControl.maxAge(java.time.Duration.ofHours(1)))
                    .body(image);
        } catch (org.springframework.web.client.RestClientException ex) {
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY).build();
        }
    }

    private static boolean isLngLat(String value) {
        if (value == null) {
            return false;
        }
        String[] parts = value.split(",");
        if (parts.length != 2) {
            return false;
        }
        try {
            double lng = Double.parseDouble(parts[0].trim());
            double lat = Double.parseDouble(parts[1].trim());
            return lng >= -180 && lng <= 180 && lat >= -90 && lat <= 90;
        } catch (NumberFormatException ex) {
            return false;
        }
    }

    /** 图片代理：参数接收后委托 {@link AmapImageProxyService}（白名单与取图逻辑在服务内）。 */
    @GetMapping("/image")
    public ResponseEntity<byte[]> image(@RequestParam String url) {
        return amapImageProxyService.proxyImage(url);
    }

    /** POI 实景照片：校验参数后委托 {@link AmapPhotoService}（多源解析与 LRU 缓存在服务内）。 */
    @GetMapping("/poi-photo")
    public ResponseEntity<Void> poiPhoto(@RequestParam String name, @RequestParam String city,
                                         @RequestParam(defaultValue = "false") boolean skipAmap) {
        if (name == null || name.isBlank() || name.length() > 64
                || city == null || city.isBlank() || city.length() > 32) {
            return ResponseEntity.badRequest().build();
        }
        String photoUrl = amapPhotoService.resolvePoiPhoto(name, city, skipAmap);
        if (photoUrl == null || photoUrl.isBlank()) {
            return ResponseEntity.notFound().build();
        }
        String proxyLocation = "/api/amap/image?url=" +
                java.net.URLEncoder.encode(photoUrl, java.nio.charset.StandardCharsets.UTF_8);
        return ResponseEntity.status(HttpStatus.FOUND).location(URI.create(proxyLocation)).build();
    }

    @GetMapping("/geocode")
    public Result<List<AmapGeocodeVO>> geocode(@RequestParam String address,
                                               @RequestParam(required = false) String city) {
        return Result.ok(amapService.geocode(address, city));
    }

    @GetMapping("/poi")
    public Result<List<AmapPoiVO>> searchPoi(@RequestParam(required = false) String keywords,
                                             @RequestParam(required = false) String city,
                                             @RequestParam(required = false) String types) {
        return Result.ok(amapService.searchPoi(keywords, city, types));
    }
}
