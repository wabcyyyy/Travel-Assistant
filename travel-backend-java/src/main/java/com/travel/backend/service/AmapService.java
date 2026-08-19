package com.travel.backend.service;

import com.travel.backend.vo.AmapGeocodeVO;
import com.travel.backend.vo.AmapPoiVO;

import java.util.List;

public interface AmapService {

    List<AmapGeocodeVO> geocode(String address, String city);

    List<AmapPoiVO> searchPoi(String keywords, String city, String types);
}