package com.travel.backend.serviceImpl;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.MediaTypeFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.net.URI;
import java.net.URISyntaxException;

/**
 * 图片代理服务：把 Unsplash/Wikimedia/高德等第三方图片转成同源响应，
 * 避免浏览器被热链、防盗链或混合内容策略拦截。
 * <p>
 * 仅放行 SSRF 白名单内的图片域名，响应统一带 6 小时缓存。
 */
@Service
public class AmapImageProxyService {

    private final RestClient imageRestClient;

    public AmapImageProxyService(@Qualifier("imageRestClient") RestClient imageRestClient) {
        this.imageRestClient = imageRestClient;
    }

    /**
     * 代理取图：校验目标 URL 的 scheme 与 host 白名单后取回图片字节；
     * 空响应返回 404，非图片类型或上游异常返回 502。
     */
    public ResponseEntity<byte[]> proxyImage(String url) {
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

    /** 上游请求头：带 UA 与 Accept，部分图床（Unsplash 等）缺 UA 会拒绝。 */
    private void imageHeaders(HttpHeaders headers) {
        headers.set(HttpHeaders.USER_AGENT, "Travel-Assistant/1.0");
        headers.set(HttpHeaders.ACCEPT, "image/avif,image/webp,image/apng,image/*,*/*;q=0.8");
    }

    /** SSRF 白名单：仅允许已知图床与高德系域名。 */
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
}
