package com.travel.backend.config;

import tools.jackson.databind.json.JsonMapper;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.http.converter.json.JacksonJsonHttpMessageConverter;
import org.springframework.web.client.RestClient;

/**
 * 外部 HTTP 客户端：Spring 6 推荐的 {@link RestClient}（替代维护模式的 RestTemplate）。
 * 超时与 Jackson 转换与历史 RestTemplate 配置对齐；生成类调用读超时 180s。
 */
@Configuration
public class RestClientConfig {

    @Bean
    public RestClient restClient(JsonMapper jsonMapper) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(3000);
        factory.setReadTimeout(180000);
        return RestClient.builder()
                .requestFactory(factory)
                .messageConverters(converters -> {
                    converters.removeIf(c -> c instanceof JacksonJsonHttpMessageConverter);
                    converters.add(new JacksonJsonHttpMessageConverter(jsonMapper));
                })
                .build();
    }

    /** 图片代理：短超时，避免 POI 图拖垮 Tomcat 线程。 */
    @Bean
    public RestClient imageRestClient() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(2500);
        factory.setReadTimeout(7000);
        return RestClient.builder()
                .requestFactory(factory)
                .build();
    }
}
