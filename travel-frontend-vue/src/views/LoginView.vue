<template>
  <div class="login-page">
    <div class="login-card">
      <!-- 左侧品牌面板 -->
      <div class="brand-panel">
        <div class="brand">
          <span class="mark"></span>
          <span class="brand-name">旅行助手</span>
          <span class="brand-en">TRAVEL ASSISTANT</span>
        </div>
        <p class="brand-lede">把下一次旅行，<br />交给一次生成。</p>
        <p class="brand-foot">AI 规划每日行程 · 预算 · 地图路线</p>
      </div>
      <!-- 右侧表单 -->
      <div class="form-panel">
        <h2 class="title">{{ isRegister ? '创建账号' : '欢迎回来' }}</h2>
        <p class="subtitle">{{ isRegister ? '注册后立即开始规划行程' : '登录以继续你的行程' }}</p>
        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" size="large">
          <el-form-item prop="username" label="用户名">
            <el-input v-model="form.username" placeholder="3-32 个字符" :prefix-icon="User" />
          </el-form-item>
          <el-form-item prop="password" label="密码">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              show-password
              :prefix-icon="Lock"
            />
          </el-form-item>
          <el-form-item v-if="isRegister" prop="nickname" label="昵称">
            <el-input v-model="form.nickname" placeholder="选填" :prefix-icon="Avatar" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="loading" style="width: 100%" @click="onSubmit">
              {{ isRegister ? '注册并登录' : '登录' }}
            </el-button>
          </el-form-item>
        </el-form>
        <div class="switch">
          <el-link type="primary" @click="toggleMode">
            {{ isRegister ? '已有账号？去登录' : '没有账号？去注册' }}
          </el-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Avatar, Lock, User } from '@element-plus/icons-vue'
// ElMessage 由 AutoImport resolver 按需注入（含样式）；表单类型仍显式声明
import type { FormInstance, FormRules } from 'element-plus'

import { login, register } from '../api'
import { useUserStore } from '../store/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const formRef = ref<FormInstance>()
const isRegister = ref(false)
const loading = ref(false)

const form = reactive({
  username: '',
  password: '',
  nickname: '',
})

const rules = computed<FormRules>(() => ({
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 32, message: '用户名长度 3-32', trigger: 'blur' },
  ],
  password: isRegister.value
    ? [
        { required: true, message: '请输入密码', trigger: 'blur' },
        { min: 6, max: 24, message: '密码长度 6-24', trigger: 'blur' },
        {
          validator: (_rule, value, callback) => {
            if (!value || value.length < 6) {
              callback()
              return
            }
            if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) {
              callback(new Error('密码需同时包含字母和数字'))
            } else {
              callback()
            }
          },
          trigger: 'blur',
        },
      ]
    : // 登录只校验非空：历史/演示账号（如管理员 123456）不应被注册策略挡住
      [{ required: true, message: '请输入密码', trigger: 'blur' }],
}))

function toggleMode() {
  isRegister.value = !isRegister.value
  formRef.value?.clearValidate()
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    if (isRegister.value) {
      await register({
        username: form.username,
        password: form.password,
        nickname: form.nickname || undefined,
      })
      ElMessage.success('注册成功')
    }
    const res = await login({ username: form.username, password: form.password })
    // 凭据在 HttpOnly Cookie；不再把 JWT 写入 localStorage/内存
    userStore.setToken('')
    userStore.setUsername(res.data.user.username)
    userStore.setRole(res.data.user.role)
    // 回跳登录前访问的页面（如分享链接 /trips/58）；仅接受站内路径防开放跳转
    const redirect = route.query.redirect
    if (typeof redirect === 'string' && redirect.startsWith('/')) {
      router.push(redirect)
    } else {
      router.push({ name: 'home' })
    }
  } catch {
    /* 错误提示已由拦截器处理 */
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 32px 16px 48px;
  min-height: calc(100vh - 108px);
}

/* 双栏卡片：墨黑品牌面板 + 白色表单 */
.login-card {
  position: relative;
  display: flex;
  width: 100%;
  max-width: 760px;
  overflow: hidden;
  border-radius: 16px;
  border: 1px solid var(--lp-border);
  background: var(--lp-surface);
  box-shadow: var(--lp-shadow-md);
}

.brand-panel {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  width: 300px;
  flex: none;
  padding: 36px 28px;
  background: linear-gradient(165deg, #0b3d39 0%, var(--lp-ink-deep) 100%);
  color: #f2f8f7;
}

.brand {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.brand .mark {
  width: 16px;
  height: 16px;
  border-radius: 5px;
  background: var(--lp-accent);
  margin-bottom: 4px;
}

.brand-name {
  font-size: 20px;
  font-weight: 800;
  letter-spacing: 0.06em;
}

.brand-en {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.22em;
  color: #9dc3be;
}

/* 手册风渐变点缀（§5.5，纯 CSS 不引入图片）：品牌名下 --lp-theme-accent 渐变细条 */
.brand::after {
  content: '';
  display: block;
  width: 48px;
  height: 3px;
  margin-top: 6px;
  border-radius: 2px;
  background: var(--lp-theme-accent);
}

.brand-lede {
  margin: 0;
  font-family: var(--lp-font-display);
  font-size: 24px;
  line-height: 1.5;
  font-weight: 700;
}

.brand-foot {
  margin: 0;
  padding-top: 14px;
  position: relative;
  font-size: 12px;
  color: #b9d4d0;
  letter-spacing: 0.04em;
}

/* 留白节奏：底部注脚上方发丝渐变线，与主题渐变条呼应 */
.brand-foot::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 1px;
  background: linear-gradient(90deg, rgb(242 248 247 / 0%), rgb(242 248 247 / 32%));
}

.form-panel {
  flex: 1;
  padding: 40px 40px 32px;
}

.form-panel :deep(.el-form-item) {
  margin-bottom: 20px;
}

/* 表单规范对齐（§5.5）：label 在上（placeholder 不作 label）、字重与全站一致 */
.form-panel :deep(.el-form-item__label) {
  font-weight: 600;
  color: var(--lp-ink-soft);
  padding-bottom: 6px;
}

/* 焦点环对齐全站规范：--lp-accent 描边 + 浅底外环 */
.form-panel :deep(.el-input__wrapper.is-focus) {
  box-shadow:
    0 0 0 1px var(--lp-accent) inset,
    0 0 0 3px var(--lp-accent-soft);
}

.form-panel :deep(.el-button) {
  letter-spacing: 0.08em;
}

.title {
  margin: 0 0 4px;
  font-size: 24px;
  font-weight: 800;
  letter-spacing: 0.04em;
}

.subtitle {
  color: var(--lp-muted);
  font-size: 13px;
  margin: 0 0 24px;
}

.switch {
  text-align: center;
  margin-top: 4px;
}

@media (max-width: 720px) {
  .login-card {
    flex-direction: column;
  }

  .brand-panel {
    width: auto;
    padding: 24px 28px;
    gap: 12px;
  }

  .brand-lede {
    font-size: 18px;
  }

  .form-panel {
    padding: 28px 20px 24px;
  }
}
</style>