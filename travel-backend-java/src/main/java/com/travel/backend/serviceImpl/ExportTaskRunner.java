package com.travel.backend.serviceImpl;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.lowagie.text.pdf.BaseFont;
import com.travel.backend.entity.BudgetDetail;
import com.travel.backend.entity.ExportTask;
import com.travel.backend.entity.ItineraryDay;
import com.travel.backend.entity.ItineraryItem;
import com.travel.backend.entity.ItineraryMain;
import com.travel.backend.mapper.BudgetDetailMapper;
import com.travel.backend.mapper.ExportTaskMapper;
import com.travel.backend.mapper.ItineraryDayMapper;
import com.travel.backend.mapper.ItineraryItemMapper;
import com.travel.backend.mapper.ItineraryMainMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ClassPathResource;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.thymeleaf.TemplateEngine;
import org.thymeleaf.context.Context;
import org.xhtmlrenderer.pdf.ITextRenderer;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.math.BigDecimal;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
public class ExportTaskRunner {

    private static final Logger log = LoggerFactory.getLogger(ExportTaskRunner.class);

    private final ExportTaskMapper taskMapper;
    private final ItineraryMainMapper mainMapper;
    private final ItineraryDayMapper dayMapper;
    private final ItineraryItemMapper itemMapper;
    private final BudgetDetailMapper budgetMapper;
    private final TemplateEngine templateEngine;
    private final String exportDir;
    private final Path fontPath;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public ExportTaskRunner(ExportTaskMapper taskMapper, ItineraryMainMapper mainMapper,
                            ItineraryDayMapper dayMapper, ItineraryItemMapper itemMapper,
                            BudgetDetailMapper budgetMapper,
                            @org.springframework.beans.factory.annotation.Qualifier("exportTemplateEngine") TemplateEngine templateEngine,
                            @Value("${app.export.dir:data/export}") String exportDir) throws Exception {
        this.taskMapper = taskMapper;
        this.mainMapper = mainMapper;
        this.dayMapper = dayMapper;
        this.itemMapper = itemMapper;
        this.budgetMapper = budgetMapper;
        this.templateEngine = templateEngine;
        this.exportDir = exportDir;
        this.fontPath = extractFont();
    }

    @Async
    public void renderPdf(Long taskId) {
        try {
            ExportTask task = taskMapper.selectById(taskId);
            if (task == null) {
                log.error("export task not found: {}", taskId);
                return;
            }
            ItineraryMain main = mainMapper.selectById(task.getItineraryId());
            Map<String, Object> model = buildModel(main);

            Context context = new Context();
            context.setVariables(model);
            String html = templateEngine.process("export/itinerary", context);

            File dir = new File(exportDir);
            if (!dir.exists() && !dir.mkdirs()) {
                throw new IllegalStateException("无法创建导出目录: " + exportDir);
            }
            Path target = dir.toPath().resolve("itinerary_" + taskId + ".pdf");
            renderPdfToFile(html, target.toFile());

            task.setStatus("DONE");
            task.setFilePath(target.toString());
            task.setFinishedAt(LocalDateTime.now());
            taskMapper.updateById(task);
            log.info("export pdf done: task={} file={}", taskId, target);
        } catch (Throwable e) {
            log.error("export pdf failed: task={}", taskId, e);
            ExportTask task = taskMapper.selectById(taskId);
            if (task != null) {
                task.setStatus("FAILED");
                task.setErrorMsg(e.getMessage() == null ? "未知错误" : e.getMessage().substring(0, Math.min(500, e.getMessage().length())));
                task.setFinishedAt(LocalDateTime.now());
                taskMapper.updateById(task);
            }
        }
    }

    private Map<String, Object> buildModel(ItineraryMain main) {
        Map<String, Object> model = new HashMap<>();
        model.put("title", main.getTitle());
        model.put("city", main.getCity());
        model.put("days", main.getDays());
        model.put("persons", main.getPersons());
        model.put("budget", main.getBudget());
        model.put("startDate", main.getStartDate());
        model.put("endDate", main.getEndDate());
        model.put("preferences", main.getPreferences());

        List<Map<String, Object>> dayList = new ArrayList<>();
        BigDecimal total = BigDecimal.ZERO;
        List<ItineraryDay> days = dayMapper.selectList(new LambdaQueryWrapper<ItineraryDay>()
                .eq(ItineraryDay::getItineraryId, main.getId())
                .orderByAsc(ItineraryDay::getDayNo));
        for (ItineraryDay day : days) {
            Map<String, Object> dayMap = new HashMap<>();
            dayMap.put("dayNo", day.getDayNo());
            dayMap.put("note", day.getNote());
            dayMap.put("travelDate", day.getTravelDate());
            addDayMetadata(dayMap, day.getMetadataJson());
            List<Map<String, Object>> items = new ArrayList<>();
            List<ItineraryItem> itemEntities = itemMapper.selectList(new LambdaQueryWrapper<ItineraryItem>()
                    .eq(ItineraryItem::getDayId, day.getId())
                    .orderByAsc(ItineraryItem::getSortNo));
            for (ItineraryItem item : itemEntities) {
                Map<String, Object> itemMap = new HashMap<>();
                itemMap.put("itemType", item.getItemType());
                itemMap.put("poiName", item.getPoiName());
                itemMap.put("startTime", item.getStartTime());
                itemMap.put("endTime", item.getEndTime());
                itemMap.put("durationMin", item.getDurationMin());
                itemMap.put("cost", item.getCost());
                itemMap.put("tag", item.getTag());
                itemMap.put("remark", item.getRemark());
                itemMap.put("openTime", item.getOpenTime());
                itemMap.put("source", item.getSource());
                itemMap.put("verificationStatus", item.getVerificationStatus());
                items.add(itemMap);
            }
            dayMap.put("items", items);
            dayList.add(dayMap);
        }
        model.put("dayList", dayList);

        List<Map<String, Object>> budgetList = new ArrayList<>();
        List<BudgetDetail> budgets = budgetMapper.selectList(new LambdaQueryWrapper<BudgetDetail>()
                .eq(BudgetDetail::getItineraryId, main.getId()));
        for (BudgetDetail budget : budgets) {
            Map<String, Object> budgetMap = new HashMap<>();
            budgetMap.put("category", budget.getCategory());
            budgetMap.put("amount", budget.getAmount());
            budgetMap.put("itemCount", budget.getItemCount());
            budgetList.add(budgetMap);
            total = total.add(budget.getAmount() == null ? BigDecimal.ZERO : budget.getAmount());
        }
        model.put("budgetList", budgetList);
        model.put("totalAmount", total);
        return model;
    }

    private void addDayMetadata(Map<String, Object> dayMap, String metadataJson) {
        if (metadataJson == null || metadataJson.isBlank()) return;
        try {
            JsonNode metadata = objectMapper.readTree(metadataJson);
            if (metadata.hasNonNull("theme")) dayMap.put("theme", metadata.get("theme").asText());
            JsonNode notes = metadata.get("practicalNotes");
            if (notes != null && notes.isArray() && notes.size() > 0) {
                List<String> texts = new ArrayList<>();
                notes.forEach(n -> { if (!n.asText().isBlank()) texts.add(n.asText()); });
                if (!texts.isEmpty()) dayMap.put("practicalNotes", String.join("；", texts));
            }
            JsonNode backups = metadata.get("backupPlan");
            if (backups != null && backups.isArray() && backups.size() > 0) {
                List<String> names = new ArrayList<>();
                backups.forEach(n -> {
                    String name = n.hasNonNull("name") ? n.get("name").asText()
                            : n.hasNonNull("title") ? n.get("title").asText() : "";
                    if (!name.isBlank()) names.add(name);
                });
                if (!names.isEmpty()) dayMap.put("backupPlan", String.join("、", names));
            }
        } catch (Exception ignored) {
            // 可选手册元数据损坏时仍导出基础行程。
        }
    }

    private void renderPdfToFile(String html, File target) throws Exception {
        ITextRenderer renderer = new ITextRenderer();
        renderer.getFontResolver().addFont(fontPath.toString(), BaseFont.IDENTITY_H, BaseFont.EMBEDDED);
        renderer.setDocumentFromString(html);
        renderer.layout();
        try (FileOutputStream fos = new FileOutputStream(target)) {
            renderer.createPDF(fos);
        }
    }

    private Path extractFont() throws Exception {
        ClassPathResource resource = new ClassPathResource("fonts/simhei.ttf");
        Path temp = Files.createTempFile("simhei", ".ttf");
        try (InputStream in = resource.getInputStream()) {
            Files.copy(in, temp, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        }
        temp.toFile().deleteOnExit();
        return temp;
    }
}
