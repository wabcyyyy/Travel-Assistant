# 多阶段：Maven 构建 → JRE 运行
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /src
COPY travel-backend-java/pom.xml ./travel-backend-java/
COPY travel-backend-java/src ./travel-backend-java/src
# 契约 schema 在仓库根（资源插件从 ../contracts 拷入 classpath）；缺了会在构建期被 enforcer 拦下
COPY contracts ./contracts
RUN mvn -q -f travel-backend-java/pom.xml -DskipTests package

FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /src/target/*.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
