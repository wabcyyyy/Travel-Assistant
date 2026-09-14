package com.travel.backend.common;

import com.networknt.schema.Error;
import com.networknt.schema.Schema;
import com.networknt.schema.SchemaRegistry;
import com.networknt.schema.SpecificationVersion;
import com.networknt.schema.dialect.BasicDialectRegistry;
import com.networknt.schema.dialect.Dialect;
import com.networknt.schema.dialect.Dialects;
import com.networknt.schema.keyword.NonValidationKeyword;
import org.springframework.core.io.ClassPathResource;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import java.io.InputStream;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 整段流式生成事件的跨语言契约校验。
 *
 * <p>schema 唯一源在 Python 侧（app/schemas/stream_events.py 导出为
 * contracts/stream_events.schema.json，CI 校验漂移），本类在 Java 侧做运行时
 * 强制校验：字段改名/缺失在流入库前即被拒绝并计数，而不是 convertValue 后
 * 静默落 null。未知事件类型属前向兼容的附加事件，仅记 debug 不视为违规。
 *
 * <p>networknt 3.x：旧的 JsonSchemaFactory/ValidationMessage 已移除，
 * 改用 SchemaRegistry + Schema#validate（返回 Error 列表，空即通过）。
 */
public final class AgentStreamContract {

    private static final String SCHEMA_RESOURCE = "contracts/stream_events.schema.json";
    private static final Set<String> KNOWN_TYPES =
            Set.of("start", "day", "day_patch", "suggestions", "done", "error");

    private final Schema schema;

    private AgentStreamContract() {
        try (InputStream in = new ClassPathResource(SCHEMA_RESOURCE).getInputStream()) {
            JsonNode schemaNode = JsonMapper.builder().build().readTree(in);
            this.schema = SchemaRegistry.withDefaultDialect(
                            SpecificationVersion.DRAFT_2020_12,
                            builder -> builder.dialectRegistry(new BasicDialectRegistry(dialectWithDiscriminator())))
                    .getSchema(schemaNode);
        } catch (Exception e) {
            // schema 缺失即契约不可用：宁可启动失败也不放行无校验的流
            throw new IllegalStateException("流事件契约 schema 加载失败: " + SCHEMA_RESOURCE, e);
        }
    }

    /**
     * Pydantic 导出的 discriminator 属 OpenAPI 系注解关键字（事件分派语义已由 oneOf + type const
     * 完整表达），显式声明为非校验关键字，否则 networknt 每次加载 schema 都打未知关键字告警。
     */
    private static Dialect dialectWithDiscriminator() {
        return Dialect.builder(Dialects.getDraft202012())
                .keyword(new NonValidationKeyword("discriminator"))
                .build();
    }

    private static final class Holder {
        private static final AgentStreamContract INSTANCE = new AgentStreamContract();
    }

    public static AgentStreamContract get() {
        return Holder.INSTANCE;
    }

    /** 是否为契约定义内的已知事件类型。 */
    public boolean isKnownType(JsonNode event) {
        return KNOWN_TYPES.contains(event.path("type").asText(""));
    }

    /** 校验事件是否符合契约；返回违规消息列表，空列表表示通过。 */
    public List<String> violations(JsonNode event) {
        List<Error> errors = schema.validate(event);
        return errors.stream().map(Error::getMessage).collect(Collectors.toList());
    }

    /** 违规摘要（日志用，最多前 5 条）。 */
    public static String summarize(List<String> errors) {
        return errors.stream().limit(5).collect(Collectors.joining("; "));
    }
}
