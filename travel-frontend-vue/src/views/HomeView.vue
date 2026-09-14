<template>
  <div class="home">
    <!-- Hero：刊物式宣言版面（全宽大衬线主张，留白即排版） -->
    <section class="hero">
      <span class="hero-rule" aria-hidden="true"></span>
      <h1>下一次旅行，<br />一次生成<span class="hero-em">可信</span>行程。</h1>
      <p class="lede">
        知识库溯源、高德实时点位、预算实时核算。<br />
        提交目的地与偏好，Agent 规划每日行程、路线与花费。
      </p>
      <div class="cta-row">
        <el-button type="primary" size="large" @click="$router.push('/generate')">
          开始生成行程
        </el-button>
        <el-button size="large" text @click="$router.push('/trips')">查看我的行程</el-button>
      </div>
    </section>

    <!-- 特稿栏：编号行式特写，替代三等分能力卡 -->
    <section class="features">
      <h2 class="section-title">它能帮你做什么</h2>
      <ol class="feature-list">
        <li v-for="f in FEATURES" :key="f.no" class="feature-row">
          <span class="lp-ordinal feature-no">{{ f.no }}</span>
          <h3 class="feature-name">{{ f.name }}</h3>
          <p class="feature-desc">{{ f.desc }}</p>
        </li>
      </ol>
    </section>

    <!-- 目的地封面墙：城名当刊名，点击携城生成 -->
    <section class="dest-wall">
      <div class="dest-head">
        <h2 class="section-title">热门目的地</h2>
        <p class="dest-sub">点击城市，带着目的地直接去生成</p>
      </div>
      <div class="dest-grid">
        <button
          v-for="c in DESTINATIONS"
          :key="c.name"
          type="button"
          class="dest-card"
          @click="goGenerate(c.name)"
        >
          <img :src="c.img" :alt="c.name" loading="lazy" />
          <div class="lp-cover-fade" aria-hidden="true"></div>
          <span class="dest-name">{{ c.name }}</span>
          <span class="dest-cta">去生成这一期</span>
        </button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'

import { DESTINATIONS } from '../constants/covers'

const router = useRouter()

/** 特稿栏：文案与产品现状对齐（点位导航走地图外链，预算为概览条+天卡小计） */
const FEATURES = [
  {
    no: '01',
    name: '引用式生成',
    desc: '知识库条目以参考资料注入生成过程，点位结合高德实时数据交叉印证，出处可查、口径一致。',
  },
  {
    no: '02',
    name: '可读的每日行程',
    desc: '跨页式逐日排版：叙事、提示与拍照机位在侧，时间轴站点列在主；点位一键跳转高德或谷歌地图。',
  },
  {
    no: '03',
    name: '预算核算',
    desc: '门票、餐饮、住宿按条目聚合，编辑后实时重算；预估总价、每日小计与明细逐层对得上。',
  },
]

function goGenerate(city: string) {
  router.push({ path: '/generate', query: { city } })
}
</script>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  gap: 48px;
  max-width: var(--lp-content, 1120px);
  margin: 0 auto;
}

/* ---------- Hero：刊物式宣言版面（全宽大衬线主张，留白即排版） ---------- */
.hero {
  padding: 24px 0 0;
}

/* 刊物小题线：替代英文眉标，一根陶土细条给出起笔位置 */
.hero-rule {
  display: block;
  width: 56px;
  height: 3px;
  margin-bottom: 20px;
  border-radius: 2px;
  background: var(--lp-accent-warm);
}

.hero h1 {
  margin: 0 0 18px;
  font-family: var(--lp-font-display);
  font-size: clamp(38px, 5.4vw, 62px);
  line-height: 1.15;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--lp-ink-deep);
}

.hero-em {
  color: var(--lp-accent);
}

.lede {
  color: var(--lp-muted);
  margin: 0 0 32px;
  font-size: 16.5px;
  line-height: 1.8;
  max-width: 36em;
}

.cta-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ---------- 特稿栏：编号行式特写（发丝线分节，无卡片框） ---------- */
.section-title {
  margin: 0 0 20px;
  font-family: var(--lp-font-display);
  font-size: 26px;
  font-weight: 600;
  color: var(--lp-ink-deep);
}

.feature-list {
  margin: 0;
  padding: 0;
  list-style: none;
  border-top: 1px solid var(--lp-rule);
}

.feature-row {
  display: grid;
  grid-template-columns: 88px 200px minmax(0, 1fr);
  gap: 18px;
  align-items: baseline;
  padding: 20px 4px;
  border-bottom: 1px solid var(--lp-rule);
  transition: background 0.15s ease;
}

.feature-row:hover {
  background: var(--lp-accent-soft);
}

.feature-no {
  font-size: 26px;
}

.feature-name {
  margin: 0;
  font-family: var(--lp-font-display);
  font-size: 18px;
  font-weight: 600;
  color: var(--lp-ink);
}

.feature-desc {
  margin: 0;
  font-size: 13px;
  line-height: 1.8;
  color: var(--lp-muted);
}

@media (max-width: 720px) {
  .feature-row {
    grid-template-columns: 56px minmax(0, 1fr);
  }

  .feature-desc {
    grid-column: 2;
  }
}

/* ---------- 目的地封面墙 ---------- */
.dest-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}

.dest-head .bento-title {
  margin: 0;
}

.dest-sub {
  margin: 0;
  font-size: 13px;
  color: var(--lp-muted);
}

.dest-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.dest-card {
  position: relative;
  height: 140px;
  padding: 0;
  border: 1px solid var(--lp-border);
  border-radius: 14px;
  overflow: hidden;
  cursor: pointer;
  background: var(--lp-sand);
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease,
    transform 0.2s ease;
}

.dest-card img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 0.4s ease;
}

.dest-card:hover {
  border-color: var(--lp-accent);
  box-shadow: var(--lp-shadow-sm);
  transform: translateY(-2px);
}

.dest-card:hover img {
  transform: scale(1.04);
}

.dest-card:focus-visible {
  outline: 2px solid var(--lp-accent);
  outline-offset: 2px;
}

.dest-name {
  position: absolute;
  left: 16px;
  bottom: 14px;
  z-index: 1;
  font-family: var(--lp-font-display);
  font-size: 22px;
  font-weight: 600;
  color: #fffdf8;
  letter-spacing: 0.04em;
  text-shadow: 0 1px 8px rgb(0 0 0 / 35%);
}

/* 行动语：hover 浮现，指向「携城生成」 */
.dest-cta {
  position: absolute;
  right: 14px;
  bottom: 16px;
  z-index: 1;
  padding: 3px 10px;
  border: 1px solid rgb(255 253 248 / 45%);
  border-radius: 999px;
  background: rgb(12 46 44 / 35%);
  backdrop-filter: blur(4px);
  font-size: 11px;
  font-weight: 600;
  color: #fffdf8;
  opacity: 0;
  transform: translateY(4px);
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.dest-card:hover .dest-cta,
.dest-card:focus-visible .dest-cta {
  opacity: 1;
  transform: none;
}

@media (prefers-reduced-motion: reduce) {
  .dest-cta {
    opacity: 1;
    transform: none;
    transition: none;
  }
}

/* ---------- 移动端 ---------- */
@media (max-width: 860px) {
  .dest-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .dest-card {
    height: 120px;
  }

  .cta-row {
    flex-wrap: wrap;
  }

  .cta-row .el-button {
    width: 100%;
  }
}

@media (max-width: 480px) {
  .dest-card {
    height: 100px;
  }

  .dest-name {
    font-size: 17px;
  }

  .hero h1 {
    font-size: 30px;
  }

  .lede {
    font-size: 15px;
  }
}
</style>
