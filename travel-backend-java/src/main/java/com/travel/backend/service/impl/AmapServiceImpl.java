package com.travel.backend.service.impl;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import com.travel.backend.common.BizException;
import com.travel.backend.service.AmapService;
import com.travel.backend.vo.AmapGeocodeVO;
import com.travel.backend.vo.AmapPoiVO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.util.UriComponentsBuilder;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

@Service
public class AmapServiceImpl implements AmapService {

    private static final Logger log = LoggerFactory.getLogger(AmapServiceImpl.class);
    private static final String GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo";
    private static final String POI_SEARCH_URL = "https://restapi.amap.com/v3/place/text";

    private final RestClient restClient;
    private final ObjectMapper objectMapper;

    @Value("${app.amap.web-key}")
    private String webKey;

    public AmapServiceImpl(RestClient restClient, ObjectMapper objectMapper) {
        this.restClient = restClient;
        this.objectMapper = objectMapper;
    }

    @Override
    public List<AmapGeocodeVO> geocode(String address, String city) {
        checkKey();
        if (!StringUtils.hasText(address)) {
            throw new BizException(400, "地址不能为空");
        }
        String url = UriComponentsBuilder.fromUriString(GEOCODE_URL)
                .queryParam("key", webKey)
                .queryParam("address", address)
                .queryParam("city", city == null ? "" : city)
                .build().encode().toUriString();
        JsonNode root = get(url);
        List<AmapGeocodeVO> result = new ArrayList<>();
        JsonNode geocodes = root.path("geocodes");
        if (geocodes.isArray()) {
            for (JsonNode node : geocodes) {
                AmapGeocodeVO vo = new AmapGeocodeVO();
                vo.setFormattedAddress(node.path("formatted_address").asText(null));
                vo.setLevel(node.path("level").asText(null));
                String location = node.path("location").asText(null);
                if (StringUtils.hasText(location)) {
                    String[] parts = location.split(",");
                    if (parts.length == 2) {
                        vo.setLongitude(new BigDecimal(parts[0]));
                        vo.setLatitude(new BigDecimal(parts[1]));
                    }
                }
                result.add(vo);
            }
        }
        return result;
    }

    @Override
    @Cacheable(cacheNames = "amap:poi", key = "'v2:' + #keywords + ':' + #city + ':' + #types")
    public List<AmapPoiVO> searchPoi(String keywords, String city, String types) {
        checkKey();
        if (!StringUtils.hasText(keywords) && !StringUtils.hasText(types)) {
            throw new BizException(400, "搜索关键字与类型至少填写一项");
        }
        UriComponentsBuilder builder = UriComponentsBuilder.fromUriString(POI_SEARCH_URL)
                .queryParam("key", webKey)
                // 返回 biz_ext（评分/人均消费），供前端做质量筛选与价位去重
                .queryParam("extensions", "all");
        if (StringUtils.hasText(keywords)) {
            builder.queryParam("keywords", keywords);
        }
        if (StringUtils.hasText(city)) {
            builder.queryParam("city", city);
        }
        if (StringUtils.hasText(types)) {
            builder.queryParam("types", types);
        }
        String url = builder.build().encode().toUriString();
        JsonNode root = get(url);
        List<AmapPoiVO> result = new ArrayList<>();
        JsonNode pois = root.path("pois");
        if (pois.isArray()) {
            for (JsonNode node : pois) {
                AmapPoiVO vo = new AmapPoiVO();
                vo.setId(node.path("id").asText(null));
                vo.setName(node.path("name").asText(null));
                vo.setAddress(node.path("address").asText(null));
                vo.setType(node.path("type").asText(null));
                JsonNode bizExt = node.path("biz_ext");
                vo.setRating(bizExt.path("rating").asText(null));
                vo.setCost(bizExt.path("cost").asText(null));
                String location = node.path("location").asText(null);
                if (StringUtils.hasText(location)) {
                    String[] parts = location.split(",");
                    if (parts.length == 2) {
                        vo.setLongitude(new BigDecimal(parts[0]));
                        vo.setLatitude(new BigDecimal(parts[1]));
                    }
                }
                result.add(vo);
            }
        }
        return result;
    }

    private void checkKey() {
        if (!StringUtils.hasText(webKey)) {
            throw new BizException(400, "未配置高德 Web 服务 key（AMAP_WEB_KEY）");
        }
    }

    private JsonNode get(String url) {
        try {
            String body = restClient.get()
                    .uri(java.net.URI.create(url))
                    .retrieve()
                    .body(String.class);
            JsonNode root = objectMapper.readTree(body);
            String status = root.path("status").asText();
            if (!"1".equals(status)) {
                log.warn("amap api error: {}", root.path("info").asText());
                throw new BizException(502, "高德地图服务暂不可用：" + root.path("info").asText());
            }
            return root;
        } catch (RestClientException e) {
            log.error("amap api request failed: {}", e.getMessage());
            throw new BizException(502, "高德地图服务暂不可用");
        } catch (Exception e) {
            log.error("amap api parse failed: {}", e.getMessage());
            throw new BizException(502, "高德地图服务响应异常");
        }
    }
}