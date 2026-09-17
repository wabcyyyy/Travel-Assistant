<template>
  <AppDialog :model-value="visible" :title="published ? '模板发布中' : '发布为模板'" width="520px" @update:model-value="onClose">
    <div class="template-dialog">
      <p class="hint">
        发布后行程将以<b>脱敏快照</b>进入模板广场：含地点骨架与花费档位，不含实际账单、备注与参与者信息。
      </p>

      <p v-if="error" class="error">{{ error }} <button type="button" @click="load">重试</button></p>
      <p v-else-if="loading" class="hint">生成预览中…</p>

      <template v-else-if="summary">
        <div class="summary-head">
          <h4>{{ summary.title }}</h4>
          <span class="hint">{{ summary.intro }}</span>
        </div>

        <ul class="tiers">
          <li v-for="tier in summary.costTiers" :key="tier.category">
            <span class="tier-category">{{ tier.category }}</span>
            <span>{{ tier.amountRangeText }}</span>
          </li>
        </ul>

        <ol class="days">
          <li v-for="day in summary.dayList" :key="day.dayNo">
            <b>D{{ day.dayNo }}</b> {{ day.theme || '' }}
            <span class="hint">{{ (day.items || []).map((item) => item.poiName).join(' → ') }}</span>
          </li>
        </ol>
      </template>

      <p class="hint" v-if="publishedAt">已发布于 {{ publishedAt.slice(0, 16).replace('T', ' ') }}</p>
    </div>

    <template #footer>
      <button v-if="!published" type="button" class="primary" :disabled="busy" @click="onPublish">
        {{ busy ? '发布中…' : '确认发布' }}
      </button>
      <button v-else type="button" class="danger" :disabled="busy" @click="onUnpublish">
        {{ busy ? '下架中…' : '下架模板' }}
      </button>
      <button type="button" @click="onClose">关闭</button>
    </template>
  </AppDialog>
</template>

<script setup lang="ts">
/** 发布对话框（C2.4）：预览脱敏投影（花费档位/骨架），确认发布或下架。 */
import { ref, watch } from 'vue'
import AppDialog from '../ui/AppDialog.vue'
import { toast } from '../ui/toast'
import { publishTemplate, unpublishTemplate } from '../../api/templates'
import type { TemplateSummaryVO } from '../../api/templates'

const props = defineProps<{
  visible: boolean
  itineraryId: number | string
  /** 源行程是否已发布（detail.templatePublishedAt 有值） */
  published: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  /** 发布/下架成功：壳层刷新详情 */
  changed: []
}>()

const summary = ref<TemplateSummaryVO | null>(null)
const publishedAt = ref<string | null>(null)
const loading = ref(false)
const busy = ref(false)
const error = ref('')

watch(
  () => props.visible,
  (visible) => {
    if (visible) void load()
  },
)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { getTemplateView } = await import('../../api/templates')
    const result = await getTemplateView(props.itineraryId)
    summary.value = result.data.summary
    publishedAt.value = result.data.publishedAt
  } catch {
    summary.value = null
    publishedAt.value = null
    error.value = '预览加载失败'
  } finally {
    loading.value = false
  }
}

async function onPublish() {
  busy.value = true
  try {
    const result = await publishTemplate(props.itineraryId)
    summary.value = result.data.summary
    publishedAt.value = result.data.publishedAt
    toast.success('已发布到模板广场')
    emit('changed')
  } catch {
    toast.error('发布失败，请重试')
  } finally {
    busy.value = false
  }
}

async function onUnpublish() {
  busy.value = true
  try {
    await unpublishTemplate(props.itineraryId)
    toast.success('已下架')
    emit('changed')
    onClose()
  } catch {
    toast.error('下架失败，请重试')
  } finally {
    busy.value = false
  }
}

function onClose() {
  emit('update:visible', false)
}
</script>

<style scoped>
.template-dialog {
  display: flex;
  flex-direction: column;
  gap: 12px;
  font-size: 14px;
  color: var(--lp-text-body);
}
.hint {
  color: var(--lp-text-muted);
  font-size: 12px;
  margin: 0;
}
.error {
  color: var(--lp-danger);
}
.summary-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.summary-head h4 {
  margin: 0;
  color: var(--lp-text-title);
}
.tiers {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.tiers li {
  display: flex;
  gap: 6px;
  border: 1px solid var(--lp-border);
  border-radius: var(--lp-radius-sm);
  padding: 4px 10px;
  font-size: 13px;
}
.tier-category {
  font-weight: 600;
}
.days {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
button.primary {
  border-color: var(--lp-accent);
  background: var(--lp-accent);
  color: var(--lp-accent-on-fill);
}
button.danger {
  border-color: var(--lp-danger);
  background: var(--lp-danger-soft);
  color: var(--lp-danger);
}
</style>
