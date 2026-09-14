package com.travel.backend.service.impl;

import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.util.UriComponentsBuilder;

import java.net.URI;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * POI 实景照片多源解析服务（含 LRU 缓存）。
 * <p>
 * 源顺序按「拍的就是该点位」的精度排列，图库（Unsplash/Pexels）为模糊检索只作最后兜底：
 * <ul>
 * <li>国内：高德实拍 → Wikipedia(zh/en/ja) → Wikimedia Commons → Unsplash → Pexels；</li>
 * <li>海外（skipAmap=true）：Wikipedia(zh/en/ja) → Wikimedia Commons → Unsplash → Pexels，
 * <b>不访问高德</b>（海外无覆盖且白耗超时），不依赖 Google API key。</li>
 * </ul>
 * 图库查询一律<b>仅用 POI 名称</b>、禁止携带城市词——否则会按城市 token 命中泛化风景图，
 * 整页卡片变成同一城市的无关照片；图库未命中时由前端回落到类别占位块，错误的图比没有图更伤观感。
 */
@Service
public class AmapPhotoService {

    private static final Logger log = LoggerFactory.getLogger(AmapPhotoService.class);

    /** 有界 LRU：防止匿名 poi-photo 被高基数 POI 名撑爆堆。 */
    private static final int PHOTO_CACHE_MAX = 2048;
    private final Map<String, String> photoCache = java.util.Collections.synchronizedMap(
            new java.util.LinkedHashMap<String, String>(256, 0.75f, true) {
                @Override
                protected boolean removeEldestEntry(Map.Entry<String, String> eldest) {
                    return size() > PHOTO_CACHE_MAX;
                }
            });

    /** 维基系熔断冷却：连接异常（如国内网络不可达）后 5 分钟内跳过，避免每张图白等超时。 */
    private static final long WIKI_COOLDOWN_MS = 5 * 60 * 1000L;
    private volatile long wikiCooldownUntil = 0L;

    private final RestClient imageRestClient;
    private final ObjectMapper objectMapper = JsonMapper.builder().build();

    @Value("${app.amap.web-key:}")
    private String amapKey;

    @Value("${app.unsplash.access-key:}")
    private String unsplashAccessKey;

    @Value("${app.pexels.access-key:}")
    private String pexelsAccessKey;

    public AmapPhotoService(@Qualifier("imageRestClient") RestClient imageRestClient) {
        this.imageRestClient = imageRestClient;
    }

    /**
     * 解析 POI 实景照片（带缓存）。命中缓存直接返回；未命中按多源顺序解析，
     * 结果为 null 时缓存空串防止反复穿透外网。返回值可能为 null/空串。
     */
    public String resolvePoiPhoto(String name, String city, boolean skipAmap) {
        String cacheKey = city + ":" + name + ":" + (skipAmap ? "u" : "ua");
        String photoUrl = photoCache.get(cacheKey);
        if (photoUrl == null) {
            photoUrl = doResolvePoiPhoto(name, city, skipAmap);
            photoCache.put(cacheKey, photoUrl == null ? "" : photoUrl);
        }
        return photoUrl;
    }

    private String doResolvePoiPhoto(String name, String city, boolean skipAmap) {
        // 1. 高德实拍（仅国内）：该 POI 在高德的真实上传图，精度最高
        if (!skipAmap) {
            try {
                String amap = amapPhoto(name, city);
                if (amap != null && !amap.isBlank()) {
                    return amap;
                }
            } catch (Exception ignored) {
                // 继续下一源
            }
        }
        // 2. Wikipedia 百科图：地标覆盖最好，免费且稳定（网络不可达时熔断跳过）
        if (wikiAvailable()) {
            try {
                String wiki = wikipediaPhoto(name);
                if (wiki != null && !wiki.isBlank()) {
                    return wiki;
                }
            } catch (Exception e) {
                markWikiDown();
            }
        }
        // 3. Wikimedia Commons：覆盖多数海外地标实景/官方图（与 Wikipedia 同源网络，共用熔断）
        if (wikiAvailable()) {
            try {
                String commons = wikimediaCommonsPhoto(name);
                if (commons != null && !commons.isBlank()) {
                    return commons;
                }
            } catch (Exception e) {
                markWikiDown();
            }
        }
        // 4/5. 图库最后兜底：模糊检索，仅名称精确命中才可信（禁止携带城市词防泛化污染）
        try {
            String unsplash = unsplashPhoto(name);
            if (unsplash != null && !unsplash.isBlank()) {
                return unsplash;
            }
        } catch (Exception ignored) {
            // 继续下一源
        }
        try {
            // Pexels 对中文查询几乎无命中：非 ASCII 名先尽量解析英文标题再搜；
            // 维基熔断期跳过 langlinks（同样走维基网络），直接用原名快速失败
            String pexels = pexelsPhoto(wikiAvailable() ? englishSearchName(name) : name);
            if (pexels != null && !pexels.isBlank()) {
                return pexels;
            }
        } catch (Exception ignored) {
            // 无图
        }
        return null;
    }

    /** 维基系（Wikipedia/Commons）是否可用：冷却期外视为可用。 */
    private boolean wikiAvailable() {
        return System.currentTimeMillis() >= wikiCooldownUntil;
    }

    /** 维基系连接异常时进入冷却期；正常未命中（HTTP 200 无图）不触发，避免误伤可达场景。 */
    private void markWikiDown() {
        wikiCooldownUntil = System.currentTimeMillis() + WIKI_COOLDOWN_MS;
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
                    JsonNode en = pages.values().iterator().next().path("langlinks").path(0).path("*");
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
     * Pexels 实景摄影图（图库兜底源）。必须用英文关键词；
     * API 文档要求 Authorization: <API_KEY>（非 Bearer）。
     * 仅用 POI 名称检索，不携带城市词——按城市 token 命中的泛化图不如无图。
     */
    private String pexelsPhoto(String query) {
        if (pexelsAccessKey == null || pexelsAccessKey.isBlank()) {
            return null;
        }
        if (query == null) {
            query = "";
        }
        String q = query.trim();
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
            log.debug("photo candidate lookup failed, falling through to next source", e);
            return null;
        }
    }

    /**
     * Wikipedia 缩略图：zh → en → ja（海外地标覆盖最好，免费且稳定）。
     * 网络异常直接上抛交由外层熔断（一个语言不可达其余语言同样不可达，无需逐语言重试白等）。
     */
    private String wikipediaPhoto(String name) throws Exception {
        String title = name == null ? "" : name.replaceAll("[（(][^（）()]*[)）]", "").trim();
        if (title.isEmpty()) {
            return null;
        }
        for (String lang : new String[]{"zh", "en", "ja"}) {
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
                JsonNode thumb = pages.values().iterator().next().path("thumbnail").path("source");
                if (!thumb.isMissingNode() && !thumb.isNull()) {
                    return thumb.asText(null);
                }
            }
        }
        return null;
    }

    /**
     * Wikimedia Commons 文件检索：覆盖多数海外地标实景/官方图。
     * 网络异常直接上抛交由外层熔断。
     */
    private String wikimediaCommonsPhoto(String name) throws Exception {
        String title = name == null ? "" : name.replaceAll("[（(][^（）()]*[)）]", "").trim();
        if (title.isEmpty()) {
            return null;
        }
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
            JsonNode info = pages.values().iterator().next().path("imageinfo").path(0);
            String thumb = info.path("thumburl").asText(null);
            if (thumb != null && !thumb.isBlank()) {
                return thumb;
            }
            return info.path("url").asText(null);
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
            log.debug("amap photo lookup failed: name={}", name, e);
            return null;
        }
        return null;
    }

    /** Unsplash 检索 POI 实景图（图库兜底源）；仅用名称检索，未配置 access key 或请求失败时返回 null。 */
    private String unsplashPhoto(String name) {
        if (unsplashAccessKey == null || unsplashAccessKey.isBlank()) {
            return null;
        }
        // 仅用名称单级查询。禁止携带城市词——否则图库会按城市 token 命中泛化风景图，
        // 同一城市所有点位都变成无关照片；名称未命中时宁可落空由前端显示占位块。
        String q = name == null ? "" : name.trim();
        if (q.isEmpty()) {
            return null;
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
            // 无图
        }
        return null;
    }
}
