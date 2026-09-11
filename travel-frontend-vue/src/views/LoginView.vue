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
        <el-form ref="formRef" :model="form" :rules="rules" label-width="0" size="large">
          <el-form-item prop="username">
            <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" />
          </el-form-item>
          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="密码"
              show-password
              :prefix-icon="Lock"
            />
          </el-form-item>
          <el-form-item v-if="isRegister" prop="nickname">
            <el-input v-model="form.nickname" placeholder="昵称（可选）" :prefix-icon="Avatar" />
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
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Avatar, Lock, User } from '@element-plus/icons-vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

import { login, register } from '../api'
import { useUserStore } from '../store/user'

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

const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 32, message: '用户名长度 3-32', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, max: 32, message: '密码长度 8-32', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (!value || value.length < 8) {
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
  ],
}

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
    router.push({ name: 'home' })
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

.brand-lede {
  margin: 0;
  font-family: var(--lp-font-display);
  font-size: 24px;
  line-height: 1.5;
  font-weight: 700;
}

.brand-foot {
  margin: 0;
  font-size: 12px;
  color: #b9d4d0;
  letter-spacing: 0.04em;
}

.form-panel {
  flex: 1;
  padding: 40px 40px 32px;
}

.form-panel :deep(.el-form-item) {
  margin-bottom: 20px;
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