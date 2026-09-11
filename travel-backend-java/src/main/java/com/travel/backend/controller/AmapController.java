package com.travel.backend.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.travel.backend.common.Result;
import com.travel.backend.service.AmapService;
import com.travel.backend.vo.AmapGeocodeVO;
import com.travel.backend.vo.AmapPoiVO;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.MediaTypeFactory;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClient;
import org.springframework.web.util.UriComponentsBuilder;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/amap")
public class AmapController {

    private final AmapService amapService;
    private final RestClient imageRestClient;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Value("${app.amap.web-key:}")
    private String amapKey;

    @Value("${app.unsplash.access-key:}")
    private String unsplashAccessKey;

    public AmapController(AmapService amapService, RestClient imageRestClient) {
        this.amapService = amapService;
        this.imageRestClient = imageRestClient;
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

    /**
     * 图片代理：把 Unsplash/Wikimedia/高德等第三方图片转成同源响应，
     * 避免浏览器被热链、防盗链或混合内容策略拦截。
     */
    @GetMapping("/image")
    public ResponseEntity<byte[]> image(@RequestParam String url) {
        try {
            URI target = new URI(url);
            String scheme = target.getScheme();
            String host = target.getHost();
            if (!("https".equalsIgnoreCase(scheme) || "http".equalsIgnoreCase(scheme))
                    || host == null || !isAllowedImageHost(host)) {
                return ResponseEntity.badRequest().build();
            }
            ResponseEntity<byte[]> response = imageRestClient.get()
                    .uri(target)
                    .headers(this::imageHeaders)
                    .retrieve()
                    .toEntity(byte[].class);
            byte[] body = response.getBody();
            if (body == null || body.length == 0) return ResponseEntity.notFound().build();
            MediaType type = response.getHeaders().getContentType();
            if (type == null) {
                type = MediaTypeFactory.getMediaType(target.getPath()).orElse(MediaType.IMAGE_JPEG);
            }
            if (!type.getType().equalsIgnoreCase("image")) {
                return ResponseEntity.status(HttpStatus.BAD_GATEWAY).build();
            }
            return ResponseEntity.ok().contentType(type)
                    .cacheControl(org.springframework.http.CacheControl.maxAge(java.time.Duration.ofHours(6)))
                    .body(body);
        } catch (URISyntaxException | org.springframework.web.client.RestClientException ex) {
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY).build();
        }
    }

    private void imageHeaders(HttpHeaders headers) {
        headers.set(HttpHeaders.USER_AGENT, "Travel-Assistant/1.0");
        headers.set(HttpHeaders.ACCEPT, "image/avif,image/webp,image/apng,image/*,*/*;q=0.8");
    }

    private boolean isAllowedImageHost(String host) {
        String normalized = host.toLowerCase(java.util.Locale.ROOT);
        return normalized.equals("images.unsplash.com")
                || normalized.endsWith(".unsplash.com")
                || normalized.equals("images.weserv.nl")
                || normalized.equals("upload.wikimedia.org")
                || normalized.endsWith(".wikimedia.org")
                || normalized.equals("restapi.amap.com")
                || normalized.endsWith(".amap.com")
                || normalized.equals("store.is.autonavi.com")
                || normalized.endsWith(".autonavi.com");
    }

    /** 有界 LRU：防止匿名 poi-photo 被高基数 POI 名撑爆堆。 */
    private static final int PHOTO_CACHE_MAX = 2048;
    private final Map<String, String> photoCache = java.util.Collections.synchronizedMap(
            new java.util.LinkedHashMap<String, String>(256, 0.75f, true) {
                @Override
                protected boolean removeEldestEntry(Map.Entry<String, String> eldest) {
                    return size() > PHOTO_CACHE_MAX;
                }
            });

    /**
     * POI 实景照片：优先 Unsplash 真实摄影图，回退高德（过滤地图位置图）。
     * 返回同源代理地址，避免浏览器直接跟随第三方 302 后被防盗链拦截。
     * skipAmap=true 时只走 Unsplash（海外目的地，高德无覆盖且易超时）。
     */
    @GetMapping("/poi-photo")
    public ResponseEntity<Void> poiPhoto(@RequestParam String name, @RequestParam String city,
                                         @RequestParam(defaultValue = "false") boolean skipAmap) {
        if (name == null || name.isBlank() || name.length() > 64
                || city == null || city.isBlank() || city.length() > 32) {
            return ResponseEntity.badRequest().build();
        }
        String cacheKey = city + ":" + name + ":" + (skipAmap ? "u" : "ua");
        String photoUrl = photoCache.get(cacheKey);
        if (photoUrl == null) {
            try {
                photoUrl = unsplashPhoto(name, city);
            } catch (Exception e) {
                photoUrl = null;
            }
            if (!skipAmap && (photoUrl == null || photoUrl.isBlank())) {
                try {
                    // name/city 来自前端，直接拼 URL 存在参数注入，统一编码构建。
                    URI poiUri = UriComponentsBuilder
                            .fromUriString("https://restapi.amap.com/v3/place/text")
                            .queryParam("keywords", name)
                            .queryParam("city", city)
                            .queryParam("citylimit", "true")
                            .queryParam("offset", 1)
                            .queryParam("page", 1)
                            .queryParam("key", amapKey)
                            .build().encode().toUri();
                    ResponseEntity<String> resp = imageRestClient.get()
                            .uri(poiUri)
                            .retrieve()
                            .toEntity(String.class);
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
        String proxyLocation = "/api/amap/image?url=" +
                java.net.URLEncoder.encode(photoUrl, java.nio.charset.StandardCharsets.UTF_8);
        return ResponseEntity.status(HttpStatus.FOUND).location(URI.create(proxyLocation)).build();
    }

    /** Unsplash 检索 POI 实景图；未配置 access key 或请求失败时返回 null。 */
    private String unsplashPhoto(String name, String city) {
        if (unsplashAccessKey == null || unsplashAccessKey.isBlank()) {
            return null;
        }
        // 只用「名称+城市」与「名称」两级查询。禁止仅用城市名兜底——否则
        // 同一城市所有点位会命中同一张泛化风景图，详情/发现更多全变成同一张。
        String[] queries = new String[] {
                (name + " " + (city == null ? "" : city)).trim(),
                name == null ? "" : name.trim(),
        };
        for (String q : queries) {
            if (q == null || q.isBlank()) {
                continue;
            }
            try {
                String encoded = java.net.URLEncoder.encode(
                        q, java.nio.charset.StandardCharsets.UTF_8);
                String url = "https://api.unsplash.com/search/photos?query=" + encoded
                        + "&per_page=1&orientation=landscape&client_id=" + unsplashAccessKey;
                ResponseEntity<String> resp = imageRestClient.get()
                        .uri(URI.create(url))
                        .retrieve()
                        .toEntity(String.class);
                JsonNode urls = objectMapper.readTree(resp.getBody())
                        .path("results").path(0).path("urls");
                String regular = urls.path("regular").asText(null);
                if (regular != null && !regular.isBlank()) {
                    return regular;
                }
            } catch (Exception e) {
                // try next query
            }
        }
        return null;
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
