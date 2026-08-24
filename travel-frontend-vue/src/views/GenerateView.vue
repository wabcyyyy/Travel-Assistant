<template>
  <div class="generate-page">
    <div class="lp-page-head">
      <span class="bar"></span>
      <h2>行程生成</h2>
      <span class="sub">填写基本信息，其余交给 Agent</span>
    </div>

    <!-- 第一栏：目的地与出行 -->
    <el-card shadow="never" class="group-card">
      <template #header>
        <span class="group-title">目的地与出行</span>
      </template>
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="100px"
        style="max-width: 560px"
      >
        <el-form-item label="目的地" prop="city">
          <el-input v-model="form.city" placeholder="例如：北京" />
        </el-form-item>
        <el-form-item label="出行日期">
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            style="width: 100%"
          />
          <span class="hint">选填；不选则由 Agent 灵活安排</span>
        </el-form-item>
        <el-form-item label="出行天数" prop="days">
          <el-input-number v-model="form.days" :min="1" :max="14" />
          <span class="hint">{{ dateRange ? '已按日期自动计算' : '未选日期时手动填写' }}</span>
        </el-form-item>
        <el-form-item label="出行人数" prop="persons">
          <el-input-number v-model="form.persons" :min="1" :max="20" />
        </el-form-item>
        <el-form-item label="预算上限">
          <el-input-number v-model="form.budget" :min="0" :step="500" />
          <span class="hint">元（可选）</span>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 第二栏：偏好设置 -->
    <el-card shadow="never" class="group-card">
      <template #header>
        <span class="group-title">偏好设置</span>
      </template>
      <el-form label-width="100px" style="max-width: 560px">
        <el-form-item label="旅行偏好">
          <el-checkbox-group v-model="form.preferences">
            <el-checkbox value="亲子">亲子</el-checkbox>
            <el-checkbox value="人文">人文</el-checkbox>
            <el-checkbox value="自然">自然</el-checkbox>
            <el-checkbox value="美食">美食</el-checkbox>
            <el-checkbox value="文化">文化</el-checkbox>
            <el-checkbox value="网红">网红</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="住宿偏好">
          <el-radio-group v-model="form.hotelTier">
            <el-radio value="">不限</el-radio>
            <el-radio value="经济型">经济型</el-radio>
            <el-radio value="舒适型">舒适型</el-radio>
            <el-radio value="高档型">高档型</el-radio>
            <el-radio value="豪华型">豪华型</el-radio>
            <el-radio value="奢华型">奢华型</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="agreeTerms">信息无误，直接生成</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" size="large" class="submit" :loading="loading" @click="onSubmit">
            生成行程
          </el-button>
        </el-form-item>
      </el-form>
      <el-alert
        v-if="errorMsg"
        :title="errorMsg"
        type="error"
        :closable="false"
        show-icon
      />
    </el-card>

    <!-- 对话框放最底下，作为额外补充 -->
    <el-card shadow="never" class="chat-card">
      <template #header>
        <span class="group-title">补充说明（可选）</span>
      </template>
      <p class="chat-tip">有特别要求？用一句话告诉我们，AI 会帮你补全或调整上面的表单。</p>
      <div v-for="(m, i) in chat" :key="i" class="chat-line" :class="m.role">
        {{ m.text }}
      </div>
      <div class="chat-input">
        <el-input
          v-model="say"
          placeholder="例如：想去杭州玩 3 天，2 个人，10 月 1 日出发"
          @keyup.enter="onSay"
        />
        <el-button type="primary" plain :loading="thinking" @click="onSay">发送</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

import { generateItinerary, clarifyTrip } from '../api'

const router = useRouter()
const formRef = ref<FormInstance>()

const chat = ref<{ role: 'user' | 'ai'; text: string }[]>([])
const say = ref('')
const thinking = ref(false)
const agreeTerms = ref(true)

const form = reactive({
  city: '',
  days: 2,
  persons: 2,
  budget: 3000,
  preferences: [] as string[],
  hotelTier: '' as string,
})

const loading = ref(false)
const errorMsg = ref('')
const dateRange = ref<[string, string] | null>(null)

// 出行天数由所选日期区间自动计算（含头含尾）；未选日期时可手填
watch(dateRange, (range) => {
  if (!range || !range[0] || !range[1]) return
  const ms = new Date(range[1]).getTime() - new Date(range[0]).getTime()
  const days = Math.round(ms / 86400000) + 1
  if (days >= 1 && days <= 14) form.days = days
})

async function onSay() {
  const msg = say.value.trim()
  if (!msg || thinking.value) return
  chat.value.push({ role: 'user', text: msg })
  say.value = ''
  thinking.value = true
  try {
    const res = await clarifyTrip({ message: msg })
    applySlots(res.data.slots || {})
    chat.value.push({
      role: 'ai',
      text: res.data.ready ? '信息齐了！点击「生成行程」即可 ✅' : res.data.question || '还有信息需要补充',
    })
  } catch {
    chat.value.push({ role: 'ai', text: '没太理解，换个说法试试？' })
  } finally {
    thinking.value = false
  }
}

function applySlots(slots: Record<string, unknown>) {
  if (slots.city) form.city = String(slots.city)
  if (slots.days) form.days = Number(slots.days)
  if (slots.persons) form.persons = Number(slots.persons)
  if (slots.start_date) {
    const s = String(slots.start_date)
    const d = new Date(s)
    d.setDate(d.getDate() + Number(slots.days || form.days) - 1)
    const pad = (n: number) => String(n).padStart(2, '0')
    dateRange.value = [s, `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`]
  }
}

const rules: FormRules = {
  city: [{ required: true, message: '请输入目的地', trigger: 'blur' }],
  days: [{ required: true, message: '请输入出行天数', trigger: 'change' }],
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  if (!agreeTerms.value) {
    ElMessage.warning('请先勾选确认')
    return
  }
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await generateItinerary({
      city: form.city,
      days: form.days,
      persons: form.persons,
      budget: form.budget,
      startDate: dateRange.value?.[0],
      endDate: dateRange.value?.[1],
      preferences: form.preferences,
      hotelTier: form.hotelTier || undefined,
    })
    router.push({ name: 'trip-detail', params: { id: res.data.id } })
  } catch (err) {
    errorMsg.value = err instanceof Error ? err.message : '生成失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.generate-page {
  max-width: 960px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.group-title {
  font-weight: 800;
  letter-spacing: 0.04em;
}

.hint {
  margin-left: 10px;
  color: var(--lp-muted);
  font-size: 12px;
}

.chat-tip {
  margin: 0 0 10px;
  color: var(--lp-muted);
  font-size: 13px;
}

.chat-line {
  padding: 6px 12px;
  border-radius: 10px;
  margin-bottom: 8px;
  max-width: 80%;
  font-size: 14px;
}

.chat-line.user {
  background: var(--lp-ink);
  color: #fff;
  margin-left: auto;
  width: fit-content;
}

.chat-line.ai {
  background: var(--lp-sand);
  color: var(--lp-ink);
  width: fit-content;
}

.chat-input {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}

.submit {
  min-width: 160px;
  font-weight: 700;
}
</style>
