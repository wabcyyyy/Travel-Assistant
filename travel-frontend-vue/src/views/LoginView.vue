<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand-panel">
        <div class="brand">
          <span class="mark" aria-hidden="true"></span>
          <span class="brand-name">旅行助手</span>
        </div>
        <p class="brand-lede">把下一次旅行，<br />交给一次生成。</p>
        <p class="brand-foot">AI 规划每日行程 · 预算 · 地图路线</p>
      </div>
      <div class="form-panel">
        <h2 class="lp-display-md title">{{ isRegister ? '创建账号' : '欢迎回来' }}</h2>
        <p class="subtitle">{{ isRegister ? '注册后立即开始规划行程' : '登录以继续你的行程' }}</p>

        <form class="fields" @submit.prevent="onSubmit">
          <div class="field">
            <label class="field-label" for="login-user">用户名</label>
            <AppInput id="login-user" v-model="form.username" placeholder="3-32 个字符" aria-label="用户名" />
            <p v-if="errors.username" class="field-error">{{ errors.username }}</p>
          </div>
          <div class="field">
            <label class="field-label" for="login-pass">密码</label>
            <AppInput
              id="login-pass"
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              aria-label="密码"
            />
            <p v-if="errors.password" class="field-error">{{ errors.password }}</p>
          </div>
          <div v-if="isRegister" class="field">
            <label class="field-label" for="login-nick">昵称</label>
            <AppInput id="login-nick" v-model="form.nickname" placeholder="选填" aria-label="昵称" />
          </div>
          <button type="submit" class="btn-primary" :disabled="loading">
            {{ loading ? '请稍候…' : isRegister ? '注册并登录' : '登录' }}
          </button>
        </form>

        <div class="switch">
          <button type="button" class="link-btn" @click="toggleMode">
            {{ isRegister ? '已有账号？去登录' : '没有账号？去注册' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { login, register } from '../api'
import AppInput from '../components/ui/AppInput.vue'
import { useUserStore } from '../store/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const isRegister = ref(false)
const loading = ref(false)

const form = reactive({
  username: '',
  password: '',
  nickname: '',
})

const errors = reactive({ username: '', password: '' })

function validate(): boolean {
  errors.username = ''
  errors.password = ''
  const u = form.username.trim()
  if (!u) errors.username = '请输入用户名'
  else if (u.length < 3 || u.length > 32) errors.username = '用户名长度 3-32'
  if (!form.password) errors.password = '请输入密码'
  else if (isRegister.value && form.password.length < 6) errors.password = '密码至少 6 位'
  return !errors.username && !errors.password
}

function toggleMode(): void {
  isRegister.value = !isRegister.value
  errors.username = ''
  errors.password = ''
}

async function onSubmit(): Promise<void> {
  if (loading.value || !validate()) return
  loading.value = true
  try {
    const username = form.username.trim()
    const nickname = form.nickname.trim()
    if (isRegister.value) {
      await register({ username, password: form.password, nickname: nickname || null })
    }
    const res = await login({ username, password: form.password })
    const user = res.data.user
    userStore.setToken('')
    userStore.setUsername(user.username)
    userStore.setRole(user.role)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    router.replace(redirect || '/')
  } catch (err) {
    errors.password = err instanceof Error ? err.message : '登录失败'
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

.login-card {
  display: flex;
  width: 100%;
  max-width: 760px;
  overflow: hidden;
  border-radius: var(--lp-radius-card);
  border: 1px solid var(--lp-edge-1);
  background: var(--lp-surface-card);
  box-shadow: var(--lp-shadow-md);
}

.brand-panel {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  width: 300px;
  flex: none;
  padding: 36px 28px;
  background: var(--lp-ink-card-bg);
  color: var(--lp-ink-card-ink);
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
  font-family: var(--lp-font-display);
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.02em;
}

.brand-lede {
  margin: 0;
  font-family: var(--lp-font-display);
  font-size: 24px;
  line-height: 1.35;
  font-weight: 600;
  letter-spacing: -0.03em;
}

.brand-foot {
  margin: 0;
  padding-top: 14px;
  position: relative;
  font-size: 12px;
  color: var(--lp-ink-card-muted);
}

.brand-foot::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 1px;
  background: color-mix(in srgb, var(--lp-ink-card-ink) 18%, transparent);
}

.form-panel {
  flex: 1;
  padding: 40px 36px;
}

.title {
  margin: 0 0 4px;
}

.subtitle {
  margin: 0 0 28px;
  color: var(--lp-text-muted);
  font-size: var(--lp-text-body);
}

.fields {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.field-label {
  display: block;
  margin-bottom: 6px;
  font-size: var(--lp-text-caption);
  font-weight: 500;
  color: var(--lp-text-muted);
}

.field-error {
  margin: 6px 0 0;
  color: var(--lp-danger);
  font-size: 12px;
}

.btn-primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-height: 44px;
  margin-top: 8px;
  border: none;
  border-radius: var(--lp-radius-sm);
  background: var(--lp-accent);
  color: var(--lp-accent-on-fill);
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
}

.btn-primary:hover:not(:disabled) {
  background: var(--lp-accent-hover);
}

.btn-primary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.switch {
  margin-top: 20px;
  text-align: center;
}

.link-btn {
  border: none;
  background: none;
  padding: 0;
  color: var(--lp-accent);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}

@media (max-width: 640px) {
  .login-card {
    flex-direction: column;
  }

  .brand-panel {
    width: auto;
    padding: 24px;
  }

  .form-panel {
    padding: 28px 22px;
  }
}
</style>
