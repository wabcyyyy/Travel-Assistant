package com.travel.backend.serviceImpl;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.util.UriComponentsBuilder;

import java.net.URI;
import java.util.Map;

/**
 * POI 实景照片多源解析服务（含 LRU 缓存）。
 * <p>
 * 国内：Unsplash → 高德（过滤地图位置图）。<br>
 * 海外（skipAmap=true）：Unsplash → Pexels(英文检索) → Wikipedia(zh/en/ja) → Wikimedia Commons，
 * <b>不访问高德</b>（海外无覆盖且白耗超时）。
 */
@Service
public class AmapPhotoService {

    /** 有界 LRU：防止匿名 poi-photo 被高基数 POI 名撑爆堆。 */
    private static final int PHOTO_CACHE_MAX = 2048;
    private final Map<String, String> photoCache = java.util.Collections.synchronizedMap(
            new java.util.LinkedHashMap<String, String>(256, 0.75f, true) {
                @Override
                protected boolean removeEldestEntry(Map.Entry<String, String> eldest) {
                    return size() > PHOTO_CACHE_MAX;
                }
            });

    private final RestClient imageRestClient;
    private final ObjectMapper objectMapper = new ObjectMapper();

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
}
