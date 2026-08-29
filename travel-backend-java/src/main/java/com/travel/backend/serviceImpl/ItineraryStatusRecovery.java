package com.travel.backend.serviceImpl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.cache.CacheManager;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

/** 修复因进程中断遗留的生成中行程，避免页面永久轮询。 */
@Slf4j
@Service
public class ItineraryStatusRecovery {

    private final ItineraryMainMapper mainMapper;
    private final ItineraryDayMapper dayMapper;
    private final ItineraryItemMapper itemMapper;
    private final CacheManager cacheManager;

    public ItineraryStatusRecovery(ItineraryMainMapper mainMapper, ItineraryDayMapper dayMapper,
                                   ItineraryItemMapper itemMapper, CacheManager cacheManager) {
        this.mainMapper = mainMapper;
        this.dayMapper = dayMapper;
        this.itemMapper = itemMapper;
        this.cacheManager = cacheManager;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void recoverOnStartup() {
        recover();
    }

    @Scheduled(fixedDelay = 60_000L, initialDelay = 60_000L)
    public void recover() {
        List<ItineraryMain> pending = mainMapper.selectList(
                new LambdaQueryWrapper<ItineraryMain>().eq(ItineraryMain::getStatus, 1));
        boolean changed = false;
        LocalDateTime staleBefore = LocalDateTime.now().minusMinutes(30);
        for (ItineraryMain main : pending) {
            List<ItineraryDay> days = dayMapper.selectList(
                    new LambdaQueryWrapper<ItineraryDay>()
                            .eq(ItineraryDay::getItineraryId, main.getId()));
            long completedDays = days.stream().filter(day -> itemMapper.selectCount(
                    new LambdaQueryWrapper<ItineraryItem>().eq(ItineraryItem::getDayId, day.getId())) > 0).count();
            if (!days.isEmpty() && completedDays == days.size() && days.size() == main.getDays()) {
                main.setStatus(2);
                main.setTitle(main.getCity() + main.getDays() + "日游");
                mainMapper.updateById(main);
                changed = true;
                log.info("recovered completed itinerary {}", main.getId());
            } else if (main.getCreatedAt() != null && main.getCreatedAt().isBefore(staleBefore)) {
                main.setStatus(3);
                main.setPlanNote("生成任务曾被中断，请新建相似行程后重试");
                mainMapper.updateById(main);
                changed = true;
                log.warn("marked stale itinerary {} as failed", main.getId());
            }
        }
        if (changed) {
            var cache = cacheManager.getCache("itinerary:detail");
            if (cache != null) cache.clear();
        }
    }
}
