<template>
  <div class="generate-page">
    <div class="lp-page-head">
      <span class="bar"></span>
      <h2>行程生成</h2>
      <span class="sub">直接说需求，或手动填写</span>
    </div>
    <el-card class="chat-card" shadow="never">
      <div v-for="(m, i) in chat" :key="i" class="chat-line" :class="m.role">
        {{ m.text }}
      </div>
      <div class="chat-input">
        <el-input
          v-model="say"
          placeholder="例如：想去杭州玩 3 天，2 个人，10 月 1 日出发"
          @keyup.enter="onSay"
        />
        <el-button type="primary" :loading="thinking" @click="onSay">发送</el-button>
      </div>
    </el-card>
    <el-card class="generate" shadow="never">
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
      <el-form-item label="起止日期">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="出行天数" prop="days">
        <el-input-number v-model="form.days" :min="1" :max="14" />
      </el-form-item>
      <el-form-item label="出行人数" prop="persons">
        <el-input-number v-model="form.persons" :min="1" :max="20" />
      </el-form-item>
      <el-form-item label="预算上限" prop="budget">
        <el-input-number v-model="form.budget" :min="0" :step="500" />
      </el-form-item>
      <el-form-item label="偏好">
        <el-select v-model="form.preferences" multiple placeholder="亲子 / 网红 / 人文..." clearable>
          <el-option label="亲子" value="亲子" />
          <el-option label="网红" value="网红" />
          <el-option label="人文" value="人文" />
          <el-option label="自然" value="自然" />
          <el-option label="美食" value="美食" />
        </el-select>
      </el-form-item>
      <el-form-item label="住宿偏好">
        <el-select v-model="form.hotelTier" placeholder="不限（默认按舒适档推荐）" clearable>
          <el-option label="经济型" value="经济型" />
          <el-option label="舒适型" value="舒适型" />
          <el-option label="高档型" value="高档型" />
          <el-option label="豪华型" value="豪华型" />
          <el-option label="奢华型" value="奢华型" />
        </el-select>
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
      style="margin-bottom: 12px"
    />
  </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { type FormInstance, type FormRules } from 'element-plus'

import { generateItinerary, clarifyTrip } from '../api'

const router = useRouter()
const formRef = ref<FormInstance>()

const chat = ref<{ role: 'user' | 'ai'; text: string }[]>([])
const say = ref('')
const thinking = ref(false)

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
      text: res.data.ready ? '信息齐了！点击下方「生成行程」即可 ✅' : res.data.question || '还有信息需要补充',
    })
  } catch {
    chat.value.push({ role: 'ai', text: '没太理解，换个说法试试？' })
  } finally {
    thinking.value = false
  }
}

const form = reactive({
  city: '',
  days: 2,
  persons: 2,
  budget: 3000,
  preferences: [] as string[],
  hotelTier: '' as string,
})

const dateRange = ref<[string, string] | null>(null)
const loading = ref(false)
const errorMsg = ref('')

const rules: FormRules = {
  city: [{ required: true, message: '请输入目的地', trigger: 'blur' }],
  days: [{ required: true, message: '请输入出行天数', trigger: 'change' }],
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
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
}

.chat-card {
  margin-bottom: 16px;
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