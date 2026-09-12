<template>
  <el-dialog :model-value="visible" title="搜索添加景点" width="560px" @update:model-value="emit('update:visible', $event)">
    <div class="search-bar">
      <el-input
        v-model="searchKeyword"
        placeholder="输入景点/餐饮关键字，如：故宫、烤鸭"
        clearable
        @keyup.enter="onSearch"
      />
      <el-button type="primary" :loading="searching" @click="onSearch">搜索</el-button>
    </div>
    <el-empty v-if="!searching && searchResults.length === 0 && searched" description="无结果" />
    <div v-for="poi in searchResults" :key="poi.id" class="poi-row">
      <div class="poi-main">
        <div class="poi-name">{{ poi.name }}</div>
        <div class="poi-addr">{{ poi.address || '暂无地址' }}</div>
      </div>
      <el-button type="primary" link @click="onAddPoi(poi)">添加</el-button>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { searchPoi, type AmapPoi } from '../../api/amap'
import { useItineraryStore } from '../../store/itinerary'
import { useItineraryActions } from '../../composables/useItineraryActions'

// 搜索添加景点对话框（M4-②b 自 DayListCard 迁出以瘦身）：检索 + 行内添加，
// 自行读写 store/actions，父级只控可见性与目标日。
const props = defineProps<{
  visible: boolean
  dayId: number
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
}>()

const store = useItineraryStore()
const actions = useItineraryActions()

const searchKeyword = ref('')
const searching = ref(false)
const searched = ref(false)
const searchResults = ref<AmapPoi[]>([])

// 每次打开重置检索状态（与迁出前 openAddDialog 行为一致）
watch(
  () => props.visible,
  (v) => {
    if (v) {
      searchKeyword.value = ''
      searchResults.value = []
      searched.value = false
    }
  },
)

async function onSearch() {
  if (!searchKeyword.value.trim()) return
  searching.value = true
  try {
    const res = await searchPoi(searchKeyword.value.trim(), store.detail?.city)
    searchResults.value = res.data
    searched.value = true
  } finally {
    searching.value = false
  }
}

async function onAddPoi(poi: AmapPoi) {
  await actions.addItem(store.detail!.id, {
    dayId: props.dayId,
    itemType: 'attraction',
    poiName: poi.name,
    poiId: poi.id,
    address: poi.address || undefined,
    latitude: poi.latitude ?? undefined,
    longitude: poi.longitude ?? undefined,
  })
  ElMessage.success(`已添加「${poi.name}」`)
  emit('update:visible', false)
}
</script>

<style scoped>
.search-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.poi-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 4px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.poi-name {
  font-weight: 600;
}

.poi-addr {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
