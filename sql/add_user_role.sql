-- 用户表增加角色字段，用于后台管理权限区分
-- 执行方式: mysql -uroot -p travel_assistant < add_user_role.sql

ALTER TABLE sys_user
    ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user' COMMENT '角色 user-普通用户 admin-管理员' AFTER status;

-- 提升管理员：把下面的占位用户名改成实际账号后，去掉注释再执行。
-- 注意：不要把真实管理员用户名提交到仓库。
-- UPDATE sys_user SET role = 'admin' WHERE username = '<admin_username>';
