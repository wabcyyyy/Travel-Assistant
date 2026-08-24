package com.travel.backend.common;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.MonthDay;

/**
 * 酒店季节定价：与 travel-agent-python app/common/season.py 保持完全一致的规则。
 */
public final class SeasonPrice {

    public static final BigDecimal PEAK_FACTOR = new BigDecimal("1.8");   // 节假日窗口
    public static final BigDecimal SUMMER_FACTOR = new BigDecimal("1.5"); // 暑期 7-8 月
    public static final BigDecimal OFF_FACTOR = new BigDecimal("0.85");   // 淡季 12/1/2 月
    public static final BigDecimal NORMAL_FACTOR = BigDecimal.ONE;

    private SeasonPrice() {
    }

    public static BigDecimal factor(LocalDate d) {
        if (d == null) {
            d = LocalDate.now();
        }
        if (inHoliday(d)) {
            return PEAK_FACTOR;
        }
        int m = d.getMonthValue();
        if (m == 7 || m == 8) {
            return SUMMER_FACTOR;
        }
        if (m == 12 || m == 1 || m == 2) {
            return OFF_FACTOR;
        }
        return NORMAL_FACTOR;
    }

    public static String label(LocalDate d) {
        if (d == null) {
            d = LocalDate.now();
        }
        if (inHoliday(d)) {
            return "节假日旺季";
        }
        int m = d.getMonthValue();
        if (m == 7 || m == 8) {
            return "暑期旺季";
        }
        if (m == 12 || m == 1 || m == 2) {
            return "淡季";
        }
        return "平季";
    }

    public static BigDecimal apply(BigDecimal base, LocalDate d) {
        return base.multiply(factor(d)).setScale(2, RoundingMode.HALF_UP);
    }

    private static boolean inHoliday(LocalDate d) {
        MonthDay md = MonthDay.from(d);
        return between(md, MonthDay.of(1, 24), MonthDay.of(2, 8))
                || between(md, MonthDay.of(4, 30), MonthDay.of(5, 5))
                || between(md, MonthDay.of(9, 30), MonthDay.of(10, 7));
    }

    private static boolean between(MonthDay md, MonthDay from, MonthDay to) {
        return !md.isBefore(from) && !md.isAfter(to);
    }
}
