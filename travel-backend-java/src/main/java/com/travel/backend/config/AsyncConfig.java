package com.travel.backend.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Bean;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.concurrent.ThreadPoolTaskExecutor;

import java.util.concurrent.Executor;
import java.util.concurrent.ThreadPoolExecutor;

@Configuration
@EnableAsync
public class AsyncConfig {

    @Bean(name = "taskExecutor")
    public Executor taskExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(4);
        executor.setMaxPoolSize(8);
        executor.setQueueCapacity(50);
        executor.setThreadNamePrefix("travel-async-");
        // 高负载时由请求线程承担任务形成反压，避免无界创建线程拖垮服务。
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.CallerRunsPolicy());
        executor.setWaitForTasksToCompleteOnShutdown(true);
        executor.setAwaitTerminationSeconds(30);
        executor.initialize();
        return executor;
    }

    /**
     * 行程生成专用线程池（H6）：整段生成对 Python 的读超时可达 180s，若与全局
     * taskExecutor 共用 CallerRunsPolicy，队列满时生成任务会退化为在 Tomcat 请求
     * 线程内同步执行，并发创建行程即可耗尽 HTTP 线程（自 DoS）。因此生成任务
     * 使用独立的有界池 + AbortPolicy，拒绝异常在提交点抛出并由上层转成 429。
     */
    @Bean(name = "generationExecutor")
    public Executor generationExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(2);
        executor.setMaxPoolSize(4);
        executor.setQueueCapacity(20);
        executor.setThreadNamePrefix("travel-generation-");
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.AbortPolicy());
        executor.setWaitForTasksToCompleteOnShutdown(true);
        executor.setAwaitTerminationSeconds(30);
        executor.initialize();
        return executor;
    }

    /**
     * 富化专用线程池（J6）：管家讲解/景点介绍是可选增强，但单次调用耗时可能很长。
     * core 1 / max 2 / queue 10 的小容量 + AbortPolicy 形成有界背压——池满即拒绝并
     * 由提交点记日志丢弃，绝不退化为占用其它线程同步执行拖垮主流程；替代原先跑在
     * 公共 ForkJoinPool（无界、无背压）上的 CompletableFuture.runAsync。
     */
    @Bean(name = "enricherExecutor")
    public Executor enricherExecutor() {
        ThreadPoolTaskExecutor executor = new ThreadPoolTaskExecutor();
        executor.setCorePoolSize(1);
        executor.setMaxPoolSize(2);
        executor.setQueueCapacity(10);
        executor.setThreadNamePrefix("travel-enricher-");
        executor.setRejectedExecutionHandler(new ThreadPoolExecutor.AbortPolicy());
        executor.setWaitForTasksToCompleteOnShutdown(true);
        executor.setAwaitTerminationSeconds(30);
        executor.initialize();
        return executor;
    }
}
