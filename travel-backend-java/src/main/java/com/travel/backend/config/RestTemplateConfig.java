package com.travel.backend.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

@Configuration
public class RestTemplateConfig {

    @Bean
    public RestTemplate restTemplate(ObjectMapper objectMapper) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(3000);
        factory.setReadTimeout(180000);
        RestTemplate restTemplate = new RestTemplate(factory);
        restTemplate.getMessageConverters()
                .removeIf(c -> c instanceof MappingJackson2HttpMessageConverter);
        restTemplate.getMessageConverters()
                .add(new MappingJackson2HttpMessageConverter(objectMapper));
        return restTemplate;
    }
}