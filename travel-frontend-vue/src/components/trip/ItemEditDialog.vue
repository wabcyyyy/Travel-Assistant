<template>
  <el-dialog :model-value="visible" title="编辑行程项" width="420px" @update:model-value="emit('update:visible', $event)">
    <el-form label-width="90px" size="default">
      <el-form-item label="开始时间">
        <!-- value-format 让字符串 "HH:mm:ss" 直接回填/写回，否则选择器把字符串当非法 Date 显示为空 -->
        <el-time-picker v-model="form.startTime" value-format="HH:mm:ss" format="HH:mm" style="width: 100%" />
      </el-form-item>
      <el-form-item label="时长(分钟)">
        <el-input-number v-model="form.durationMin" :min="0" style="width: 100%" />
      </el-form-item>
      <el-form-item label="单人费用">
        <el-input-number v-model="form.cost" :min="0" :precision="2" style="width: 100%" />
      </el-form-item>
      <el-form-item label="标签">
        <el-input v-model="form.tag" placeholder="如：人文 / 网红 / 亲子" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.remark" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { useItineraryActions } from '../../composables/useItineraryActions'
import type { TripItem } from '../../types/itinerary'

// 编辑行程项对话框（M4-②b 自 DayListCard 迁出以瘦身）：表单与 PUT 更新自包含，
// 父级只传目标项与可见性。PUT 按完整地点信息更新，一并带回不可见字段避免丢坐标。
const props = defineProps<{
  visible: boolean
  item: TripItem | null
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
}>()

const actions = useItineraryActions()
const saving = ref(false)
const form = reactive({
  startTime: null as string | null,
  durationMin: null as number | null,
  cost: null as number | null,
  tag: '',
  remark: '',
})

// 打开时以目标项回填表单
watch(
  () => [props.visible, props.item] as const,
  ([visible, item]) => {
    if (visible && item) {
      form.startTime = item.startTime || null
      form.durationMin = item.durationMin ?? null
      form.cost = item.cost ?? null
      form.tag = item.tag || ''
      form.remark = item.remark || ''
    }
  },
  { immediate: true },
)

async function onSave() {
  const item = props.item
  if (!item) return
  saving.value = true
  try {
    await actions.updateItem(item.id!, {
      itemType: item.itemType,
      poiName: item.poiName,
      poiId: item.poiId,
      address: item.address,
      latitude: item.latitude,
      longitude: item.longitude,
      startTime: form.startTime || undefined,
      endTime: item.endTime,
      durationMin: form.durationMin ?? undefined,
      cost: form.cost ?? undefined,
      tag: form.tag || undefined,
      remark: form.remark || undefined,
    })
    emit('update:visible', false)
    ElMessage.success('已保存')
  } finally {
    saving.value = false
  }
}
</script>
