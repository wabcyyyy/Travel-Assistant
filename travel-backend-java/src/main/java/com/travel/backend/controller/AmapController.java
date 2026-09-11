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

    @Value("${app.pexels.access-key:}")
    private String pexelsAccessKey;

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
                || normalized.equals("images.pexels.com")
                || normalized.endsWith(".pexels.com")
                || normalized.equals("images.weserv.nl")
                || normalized.equals("upload.wikimedia.org")
                || normalized.endsWith(".wikimedia.org")
                || normalized.endsWith(".wikipedia.org")
                || normalized.equals("wikipedia.org")
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
     * POI 实景照片。
     * <p>
     * 国内：Unsplash → 高德（过滤地图位置图）。<br>
     * 海外（skipAmap=true）：Unsplash → Pexels(英文检索) → Wikipedia(zh/en/ja) → Wikimedia Commons，
     * <b>不访问高德</b>（海外无覆盖且白耗超时）。
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
            photoUrl = resolvePoiPhoto(name, city, skipAmap);
            photoCache.put(cacheKey, photoUrl == null ? "" : photoUrl);
        }
        if (photoUrl == null || photoUrl.isBlank()) {
            return ResponseEntity.notFound().build();
        }
        String proxyLocation = "/api/amap/image?url=" +
                java.net.URLEncoder.encode(photoUrl, java.nio.charset.StandardCharsets.UTF_8);
        return ResponseEntity.status(HttpStatus.FOUND).location(URI.create(proxyLocation)).build();
    }

    private String resolvePoiPhoto(String name, String city, boolean skipAmap) {
        try {
            String url = unsplashPhoto(name, city);
            if (url != null && !url.isBlank()) {
                return url;
            }
        } catch (Exception ignored) {
            // 继续下一源
        }
        // Pexels 对中文查询几乎无命中：非 ASCII 名先尽量解析英文标题再搜
        try {
            String pexelsQuery = englishSearchName(name);
            String pexels = pexelsPhoto(pexelsQuery, city);
            if (pexels != null && !pexels.isBlank()) {
                return pexels;
            }
        } catch (Exception ignored) {
            // 继续下一源
        }
        if (skipAmap) {
            String wiki = wikipediaPhoto(name);
            if (wiki != null && !wiki.isBlank()) {
                return wiki;
            }
            return wikimediaCommonsPhoto(name);
        }
        try {
            String amap = amapPhoto(name, city);
            if (amap != null && !amap.isBlank()) {
                return amap;
            }
        } catch (Exception ignored) {
            // 国内兜底失败则再试百科
        }
        String wiki = wikipediaPhoto(name);
        return (wiki != null && !wiki.isBlank()) ? wiki : wikimediaCommonsPhoto(name);
    }

    /** 名称含中文/日文等时，尝试经 Wikipedia langlinks 取英文标题，供 Pexels/Unsplash 使用。 */
    private String englishSearchName(String name) {
        if (name == null || name.isBlank()) {
            return name;
        }
        boolean nonAscii = name.chars().anyMatch(c -> c > 127);
        if (!nonAscii) {
            return name.trim();
        }
        for (String lang : new String[]{"zh", "ja"}) {
            try {
                URI uri = UriComponentsBuilder
                        .fromUriString("https://" + lang + ".wikipedia.org/w/api.php")
                        .queryParam("action", "query")
                        .queryParam("titles", name)
                        .queryParam("prop", "langlinks")
                        .queryParam("lllang", "en")
                        .queryParam("format", "json")
                        .build().encode().toUri();
                ResponseEntity<String> resp = imageRestClient.get().uri(uri)
                        .header("User-Agent", "TravelAssistantDemo/1.0")
                        .retrieve().toEntity(String.class);
                JsonNode pages = objectMapper.readTree(resp.getBody()).path("query").path("pages");
                if (pages.isObject()) {
                    JsonNode en = pages.elements().next().path("langlinks").path(0).path("*");
                    if (!en.isMissingNode() && !en.isNull()) {
                        String title = en.asText("").trim();
                        if (!title.isEmpty()) {
                            return title;
                        }
                    }
                }
            } catch (Exception ignored) {
                // 下一语言
            }
        }
        return name.trim();
    }

    /**
     * Pexels 实景摄影图（海外推荐源之一）。必须用英文关键词；
     * API 文档要求 Authorization: <API_KEY>（非 Bearer）。
     */
    private String pexelsPhoto(String query, String city) {
        if (pexelsAccessKey == null || pexelsAccessKey.isBlank()) {
            return null;
        }
        if (query == null) {
            query = "";
        }
        if (city == null) {
            city = "";
        }
        StringBuilder qb = new StringBuilder();
        String q1 = query.trim();
        String q2 = city.trim();
        if (!q1.isEmpty()) {
            qb.append(q1);
        }
        if (!q2.isEmpty()) {
            if (qb.length() > 0) {
                qb.append(' ');
            }
            qb.append(q2);
        }
        String q = qb.toString();
        if (q.isEmpty()) {
            return null;
        }
        try {
            URI uri = UriComponentsBuilder
                    .fromUriString("https://api.pexels.com/v1/search")
                    .queryParam("query", q)
                    .queryParam("per_page", 1)
                    .queryParam("orientation", "landscape")
                    .build().encode().toUri();
            ResponseEntity<String> resp = imageRestClient.get().uri(uri)
                    .header("Authorization", pexelsAccessKey)
                    .retrieve().toEntity(String.class);
            JsonNode photo = objectMapper.readTree(resp.getBody()).path("photos").path(0);
            String url = photo.path("src").path("large").asText(null);
            if (url == null || url.isBlank()) {
                url = photo.path("src").path("medium").asText(null);
            }
            return url;
        } catch (Exception e) {
            return null;
        }
    }

    /** Wikipedia 缩略图：zh → en → ja（海外地标覆盖最好，免费且稳定）。 */
    private String wikipediaPhoto(String name) {
        String title = name == null ? "" : name.replaceAll("[（(][^（）()]*[)）]", "").trim();
        if (title.isEmpty()) {
            return null;
        }
        for (String lang : new String[]{"zh", "en", "ja"}) {
            try {
                URI uri = UriComponentsBuilder
                        .fromUriString("https://" + lang + ".wikipedia.org/w/api.php")
                        .queryParam("action", "query")
                        .queryParam("generator", "search")
                        .queryParam("gsrsearch", title)
                        .queryParam("gsrlimit", 1)
                        .queryParam("prop", "pageimages")
                        .queryParam("piprop", "thumbnail")
                        .queryParam("pithumbsize", 640)
                        .queryParam("format", "json")
                        .build().encode().toUri();
                ResponseEntity<String> resp = imageRestClient.get().uri(uri)
                        .header("User-Agent", "TravelAssistantDemo/1.0")
                        .retrieve().toEntity(String.class);
                JsonNode pages = objectMapper.readTree(resp.getBody()).path("query").path("pages");
                if (pages.isObject()) {
                    JsonNode thumb = pages.elements().next().path("thumbnail").path("source");
                    if (!thumb.isMissingNode() && !thumb.isNull()) {
                        return thumb.asText(null);
                    }
                }
            } catch (Exception ignored) {
                // 试下一语言
            }
        }
        return null;
    }

    /** Wikimedia Commons 文件检索：覆盖多数海外地标实景/官方图。 */
    private String wikimediaCommonsPhoto(String name) {
        String title = name == null ? "" : name.replaceAll("[（(][^（）()]*[)）]", "").trim();
        if (title.isEmpty()) {
            return null;
        }
        try {
            URI uri = UriComponentsBuilder
                    .fromUriString("https://commons.wikimedia.org/w/api.php")
                    .queryParam("action", "query")
                    .queryParam("generator", "search")
                    .queryParam("gsrsearch", title)
                    .queryParam("gsrnamespace", 6)
                    .queryParam("gsrlimit", 1)
                    .queryParam("prop", "imageinfo")
                    .queryParam("iiprop", "url")
                    .queryParam("iiurlwidth", 640)
                    .queryParam("format", "json")
                    .build().encode().toUri();
            ResponseEntity<String> resp = imageRestClient.get().uri(uri)
                    .header("User-Agent", "TravelAssistantDemo/1.0")
                    .retrieve().toEntity(String.class);
            JsonNode pages = objectMapper.readTree(resp.getBody()).path("query").path("pages");
            if (pages.isObject()) {
                JsonNode info = pages.elements().next().path("imageinfo").path(0);
                String thumb = info.path("thumburl").asText(null);
                if (thumb != null && !thumb.isBlank()) {
                    return thumb;
                }
                return info.path("url").asText(null);
            }
        } catch (Exception ignored) {
            // 无图
        }
        return null;
    }

    /** 高德 POI 照片（仅国内）。 */
    private String amapPhoto(String name, String city) {
        try {
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
            JsonNode poi = objectMapper.readTree(resp.getBody()).path("pois").path(0);
            JsonNode photos = poi.path("photos");
            if (photos.isArray()) {
                for (JsonNode photo : photos) {
                    String title = photo.path("title").asText("");
                    String candidate = photo.path("url").asText(null);
                    if (candidate != null && !candidate.isBlank()
                            && !title.contains("地图") && !title.contains("位置")) {
                        return candidate;
                    }
                }
            }
        } catch (Exception e) {
            return null;
        }
        return null;
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
