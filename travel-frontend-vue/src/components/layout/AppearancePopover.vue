<template>
  <el-popover placement="bottom-end" :width="248" trigger="click" :teleported="false">
    <template #reference>
      <button type="button" class="appearance-trigger" aria-label="外观设置" title="外观设置">
        <el-icon :size="16"><Brush /></el-icon>
      </button>
    </template>

    <div class="appearance-panel">
      <p class="group-label">配色</p>
      <div class="swatch-row">
        <button
          v-for="scheme in SCHEMES"
          :key="scheme.id"
          type="button"
          class="swatch"
          :class="{ active: config.scheme === scheme.id }"
          :style="{ background: config.dark ? scheme.swatch.dark : scheme.swatch.light }"
          :aria-label="`配色：${scheme.id}`"
          :aria-pressed="config.scheme === scheme.id"
          @click="setScheme(scheme.id)"
        />
      </div>

      <p class="group-label">显示</p>
      <div class="toggle-row">
        <span>暗色模式</span>
        <el-switch :model-value="config.dark" @change="onDarkChange" />
      </div>
      <div class="toggle-row">
        <span>紧凑密度</span>
        <el-switch :model-value="config.density === 'compact'" @change="onDensityChange" />
      </div>
      <div class="toggle-row">
        <span>减弱动效</span>
        <el-switch :model-value="config.reduceMotion" @change="onReduceMotionChange" />
      </div>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Brush } from '@element-plus/icons-vue'

import { SCHEMES } from '../../constants/schemes'
import {
  applyAppearance,
  readAppearance,
  saveAppearance,
  type AppearanceConfig,
  type SchemeId,
} from '../../styles/appearance'

// 外观面板：每次修改先落存储再写 DOM（applyAppearance 是唯一运行时入口）
const config = ref<AppearanceConfig>(readAppearance())

function update(patch: Partial<AppearanceConfig>): void {
  config.value = saveAppearance({ ...config.value, ...patch })
  applyAppearance(document.documentElement, config.value)
}

function setScheme(scheme: SchemeId): void {
  update({ scheme })
}

function onDarkChange(value: string | number | boolean): void {
  update({ dark: value === true })
}

function onDensityChange(value: string | number | boolean): void {
  update({ density: value === true ? 'compact' : 'comfortable' })
}

function onReduceMotionChange(value: string | number | boolean): void {
  update({ reduceMotion: value === true })
}
</script>

<style scoped>
.appearance-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  /* 图标幽灵钮：顶栏不放描边盒子（描边按钮成排出现是「后台模板」观感的来源之一） */
  border: none;
  border-radius: var(--lp-radius-sm);
  background: transparent;
  color: var(--lp-text-muted);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.appearance-trigger:hover {
  background: color-mix(in srgb, var(--lp-text-1) 6%, transparent);
  color: var(--lp-text-1);
}

.appearance-panel {
  display: flex;
  flex-direction: column;
  gap: var(--lp-space-2);
}

.group-label {
  margin: var(--lp-space-1) 0 0;
  font-size: var(--lp-text-caption);
  font-weight: 700;
  color: var(--lp-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.swatch-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--lp-space-2);
}

.swatch {
  width: 26px;
  height: 26px;
  border: 2px solid transparent;
  border-radius: 50%;
  cursor: pointer;
  outline-offset: 2px;
}

.swatch.active {
  border-color: var(--lp-text-1);
}

.toggle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: var(--lp-text-2);
}
</style>
