package com.travel.backend.service;

import com.travel.backend.entity.BudgetDetail;

import java.util.List;

public interface BudgetEngine {

    List<BudgetDetail> recalculate(Long itineraryId);
}