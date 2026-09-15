<template>
  <el-dialog
    :model-value="visible"
    title="更换封面"
    width="640px"
    @update:model-value="emit('update:visible', $event)"
    @open="onOpen"
  >
    <el-tabs v-model="tab">
      <el-tab-pane label="图库搜索" name="gallery">
        <div class="search-row">
          <el-input
            v-model="keyword"
            placeholder="搜图库（如 Hangzhou West Lake；英文命中率更高）"
            clearable
            @keyup.enter="search"
          />
          <el-button type="primary" :loading="searching" @click="search">搜索</el-button>
        </div>

        <p v-if="keyMissing" class="hint">
          封面图库未配置（UNSPLASH_ACCESS_KEY），请改用「上传图片」
        </p>
        <div v-else v-loading="searching" class="gallery">
          <button
            v-for="item in results"
            :key="item.unsplashId"
            type="button"
            class="cell"
            :class="{ active: picked === item.unsplashId }"
            :aria-pressed="picked === item.unsplashId"
            @click="picked = item.unsplashId"
          >
            <img :src="item.thumb || ''" :alt="`Photo by ${item.author ?? 'Unsplash'}`" loading="lazy" />
            <span class="cell-credit">Photo · {{ item.author ?? 'Unsplash' }}</span>
          </button>
          <p v-if="searched && !results.length" class="hint">没有结果，换个关键词试试</p>
          <p v-else-if="!searched" class="hint">
            输入关键词搜索图库；选定后由服务端下载、压缩并落盘（不再依赖外站）
          </p>
        </div>

        <div class="pane-actions">
          <el-button type="primary" :disabled="!picked" :loading="saving" @click="applyUnsplash">
            设为封面
          </el-button>
          <el-button :loading="saving" @click="applyDefault">恢复默认封面</el-button>
        </div>
      </el-tab-pane>

      <el-tab-pane label="上传图片" name="upload">
        <input class="file-input" type="file" accept="image/jpeg,image/png" @change="onFileChange" />
        <p class="hint">支持 jpeg / png，≤5MB；服务端会校验类型并流式截断超限请求</p>
        <div v-if="previewUrl" class="upload-preview"><img :src="previewUrl" alt="封面预览" /></div>
        <div class="pane-actions">
          <el-button type="primary" :disabled="!file" :loading="saving" @click="applyUpload">
            上传并设为封面
          </el-button>
        </div>
      </el-tab-pane>
    </el-tabs>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref } from 'vue'

import { searchCovers, setCover, uploadCover, type CoverSearchItem } from '../../api/covers'
import type { ItineraryDetail } from '../../types/itinerary'

const props = defineProps<{
  visible: boolean
  itineraryId: number
  /** 打开时若尚未搜索过，用城市名做一次默认搜索 */
  defaultQuery?: string
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  updated: [detail: ItineraryDetail]
}>()

const tab = ref<'gallery' | 'upload'>('gallery')
const keyword = ref('')
const results = ref<CoverSearchItem[]>([])
const picked = ref<string | null>(null)
const searched = ref(false)
const searching = ref(false)
const saving = ref(false)
const keyMissing = ref(false)
const file = ref<File | null>(null)
const previewUrl = ref('')

const MAX_UPLOAD_BYTES = 5 * 1024 * 1024

async function onOpen(): Promise<void> {
  if (!searched.value && props.defaultQuery && !keyword.value) {
    keyword.value = props.defaultQuery
    await search()
  }
}

async function search(): Promise<void> {
  const q = keyword.value.trim()
  if (!q || searching.value) return
  searching.value = true
  try {
    const res = await searchCovers(q)
    results.value = res.data.items ?? []
    searched.value = true
    picked.value = null
  } catch (err) {
    const message = err instanceof Error ? err.message : ''
    if (message.includes('未配置')) keyMissing.value = true
  } finally {
    searching.value = false
  }
}

async function applyUnsplash(): Promise<void> {
  if (!picked.value || saving.value) return
  saving.value = true
  try {
    const res = await setCover(props.itineraryId, { source: 'unsplash', unsplashId: picked.value })
    ElMessage.success('封面已更新')
    emit('updated', res.data)
    emit('update:visible', false)
  } catch {
    /* 拦截器已提示（未配 key / 下载失败等） */
  } finally {
    saving.value = false
  }
}

async function applyDefault(): Promise<void> {
  if (saving.value) return
  saving.value = true
  try {
    const res = await setCover(props.itineraryId, { source: 'default' })
    ElMessage.success('已恢复默认封面')
    emit('updated', res.data)
    emit('update:visible', false)
  } catch {
    /* 拦截器已提示 */
  } finally {
    saving.value = false
  }
}

function onFileChange(event: Event): void {
  const input = event.target as HTMLInputElement
  const selected = input.files?.[0] ?? null
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = selected ? URL.createObjectURL(selected) : ''
  if (selected && selected.size > MAX_UPLOAD_BYTES) {
    ElMessage.warning('图片不能超过 5MB')
    file.value = null
    return
  }
  file.value = selected
  input.value = ''
}

async function applyUpload(): Promise<void> {
  if (!file.value || saving.value) return
  saving.value = true
  try {
    const res = await uploadCover(props.itineraryId, file.value)
    ElMessage.success('封面已更新')
    emit('updated', res.data)
    emit('update:visible', false)
  } catch {
    /* 拦截器已提示（类型/超限/网络） */
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.search-row {
  display: flex;
  gap: var(--lp-space-2);
  margin-bottom: var(--lp-space-3);
}

.gallery {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--lp-space-2);
  min-height: 120px;
}

.cell {
  position: relative;
  padding: 0;
  border: 2px solid transparent;
  border-radius: var(--lp-radius-input);
  overflow: hidden;
  cursor: pointer;
  background: var(--lp-surface-2);
  aspect-ratio: 4 / 3;
}

.cell img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.cell.active {
  border-color: var(--lp-accent);
}

.cell-credit {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 2px 6px;
  font-size: 10px;
  color: var(--lp-text-inverse);
  background: var(--lp-overlay);
  text-align: left;
}

.file-input {
  display: block;
  margin-bottom: var(--lp-space-2);
}

.upload-preview {
  margin: var(--lp-space-2) 0;
  max-width: 320px;
  border: 1px solid var(--lp-edge-1);
  border-radius: var(--lp-radius-input);
  overflow: hidden;
}

.upload-preview img {
  display: block;
  width: 100%;
}

.hint {
  margin: var(--lp-space-2) 0;
  font-size: var(--lp-text-caption);
  color: var(--lp-text-muted);
}

.pane-actions {
  margin-top: var(--lp-space-3);
  display: flex;
  gap: var(--lp-space-2);
}
</style>
