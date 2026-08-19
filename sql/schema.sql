CREATE DATABASE IF NOT EXISTS travel_assistant DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE travel_assistant;

DROP TABLE IF EXISTS budget_detail;
DROP TABLE IF EXISTS itinerary_item;
DROP TABLE IF EXISTS itinerary_day;
DROP TABLE IF EXISTS itinerary_main;
DROP TABLE IF EXISTS sys_user;
DROP TABLE IF EXISTS poi_knowledge;
DROP TABLE IF EXISTS city_consumption;

CREATE TABLE sys_user (
    id          BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
    username    VARCHAR(64)  NOT NULL COMMENT '用户名',
    password    VARCHAR(128) NOT NULL COMMENT 'BCrypt 加密密码',
    nickname    VARCHAR(64)  DEFAULT NULL COMMENT '昵称',
    phone       VARCHAR(20)  DEFAULT NULL COMMENT '手机号',
    status      TINYINT      NOT NULL DEFAULT 1 COMMENT '状态 1-正常 0-禁用',
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted     TINYINT      NOT NULL DEFAULT 0 COMMENT '逻辑删除 0-未删 1-已删',
    PRIMARY KEY (id),
    UNIQUE KEY uk_username (username)
) ENGINE = InnoDB COMMENT '用户表';

CREATE TABLE itinerary_main (
    id          BIGINT       NOT NULL AUTO_INCREMENT,
    user_id     BIGINT       NOT NULL COMMENT '所属用户',
    title       VARCHAR(128) NOT NULL COMMENT '行程标题',
    city        VARCHAR(64)  NOT NULL COMMENT '目的地城市',
    start_date  DATE         DEFAULT NULL COMMENT '开始日期',
    end_date    DATE         DEFAULT NULL COMMENT '结束日期',
    days        INT          NOT NULL DEFAULT 1 COMMENT '行程天数',
    persons     INT          NOT NULL DEFAULT 1 COMMENT '出行人数',
    budget      DECIMAL(12, 2) DEFAULT NULL COMMENT '用户预算上限',
    preferences VARCHAR(512) DEFAULT NULL COMMENT '偏好标签，逗号分隔',
    status      TINYINT      NOT NULL DEFAULT 1 COMMENT '1-草稿 2-已生成 3-已取消',
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted     TINYINT      NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY idx_user (user_id),
    KEY idx_city (city)
) ENGINE = InnoDB COMMENT '行程主表';

CREATE TABLE itinerary_day (
    id            BIGINT      NOT NULL AUTO_INCREMENT,
    itinerary_id  BIGINT      NOT NULL COMMENT '行程主表 ID',
    day_no        INT         NOT NULL COMMENT '第几天，从 1 开始',
    travel_date   DATE        DEFAULT NULL COMMENT '当日日期',
    city          VARCHAR(64) DEFAULT NULL COMMENT '当日所在城市',
    note          VARCHAR(512) DEFAULT NULL COMMENT '当日备注',
    created_at    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted       TINYINT     NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY idx_itinerary (itinerary_id)
) ENGINE = InnoDB COMMENT '日行程表';

CREATE TABLE itinerary_item (
    id            BIGINT         NOT NULL AUTO_INCREMENT,
    day_id        BIGINT         NOT NULL COMMENT '日行程 ID',
    itinerary_id  BIGINT         NOT NULL,
    item_type     VARCHAR(16)    NOT NULL COMMENT 'attraction-景点 food-餐饮 hotel-酒店 transport-交通',
    poi_name      VARCHAR(128)   NOT NULL COMMENT '地点名称',
    poi_id        VARCHAR(64)    DEFAULT NULL COMMENT '高德 POI ID',
    address       VARCHAR(255)   DEFAULT NULL,
    latitude      DECIMAL(10, 6) DEFAULT NULL,
    longitude     DECIMAL(10, 6) DEFAULT NULL,
    start_time    TIME           DEFAULT NULL COMMENT '计划开始时间',
    end_time      TIME           DEFAULT NULL COMMENT '计划结束时间',
    duration_min  INT            DEFAULT NULL COMMENT '建议游玩时长(分钟)',
    cost          DECIMAL(10, 2) DEFAULT NULL COMMENT '预估费用(单人)',
    tag           VARCHAR(32)    DEFAULT NULL COMMENT '标签：亲子/网红/人文等',
    remark        VARCHAR(255)   DEFAULT NULL,
    sort_no       INT            NOT NULL DEFAULT 0 COMMENT '当日排序',
    created_at    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted       TINYINT        NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY idx_day (day_id),
    KEY idx_itinerary (itinerary_id)
) ENGINE = InnoDB COMMENT '行程项表';

CREATE TABLE budget_detail (
    id           BIGINT         NOT NULL AUTO_INCREMENT,
    itinerary_id BIGINT         NOT NULL,
    day_id       BIGINT         DEFAULT NULL COMMENT '可为空表示整行程汇总',
    category     VARCHAR(16)    NOT NULL COMMENT '门票/餐饮/酒店/交通',
    amount       DECIMAL(12, 2) NOT NULL COMMENT '该分类金额(总价)',
    item_count   INT            NOT NULL DEFAULT 0 COMMENT '明细条数',
    remark       VARCHAR(255)   DEFAULT NULL,
    created_at   DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted      TINYINT        NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    KEY idx_itinerary (itinerary_id)
) ENGINE = InnoDB COMMENT '预算明细表';

CREATE TABLE poi_knowledge (
    id            BIGINT         NOT NULL AUTO_INCREMENT,
    city          VARCHAR(64)    NOT NULL COMMENT '所属城市',
    name          VARCHAR(128)   NOT NULL COMMENT '景点/地点名称',
    category      VARCHAR(16)    NOT NULL DEFAULT 'attraction' COMMENT 'attraction/food/hotel',
    address       VARCHAR(255)   DEFAULT NULL,
    latitude      DECIMAL(10, 6) DEFAULT NULL,
    longitude     DECIMAL(10, 6) DEFAULT NULL,
    ticket_price  DECIMAL(10, 2) DEFAULT NULL COMMENT '门票参考价，NULL 表示免费或未知',
    duration_min  INT            DEFAULT NULL COMMENT '建议游玩时长(分钟)',
    open_time     VARCHAR(64)    DEFAULT NULL COMMENT '开放时间文本',
    tags          VARCHAR(128)   DEFAULT NULL COMMENT '偏好标签，逗号分隔',
    rating        DECIMAL(2, 1)  DEFAULT NULL COMMENT '评分 0-5',
    description   VARCHAR(512)   DEFAULT NULL,
    PRIMARY KEY (id),
    KEY idx_city (city),
    KEY idx_tags (tags)
) ENGINE = InnoDB COMMENT '景点知识库(种子数据，幻觉检测对照)';

CREATE TABLE city_consumption (
    id          BIGINT         NOT NULL AUTO_INCREMENT,
    city        VARCHAR(64)    NOT NULL COMMENT '城市',
    level       VARCHAR(16)    NOT NULL DEFAULT 'standard' COMMENT '消费水平档位',
    meal_price  DECIMAL(10, 2) NOT NULL COMMENT '人均每餐参考(元)',
    transport_price DECIMAL(10, 2) NOT NULL COMMENT '日均市内交通(元)',
    hotel_price DECIMAL(10, 2) NOT NULL COMMENT '单间/晚参考(元)',
    PRIMARY KEY (id),
    UNIQUE KEY uk_city (city)
) ENGINE = InnoDB COMMENT '城市消费系数表(预算计算口径来源)';
