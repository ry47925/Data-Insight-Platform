<template>
  <el-dialog
    v-model="visible"
    class="usage-guide-dialog"
    width="960px"
    top="5vh"
    :close-on-click-modal="false"
    destroy-on-close
    aria-label="使用说明"
  >
    <template #header>
      <div class="guide-header">
        <el-icon :size="20" style="color: var(--primary);"><Reading /></el-icon>
        <span class="guide-header-title">使用说明</span>
        <span class="guide-header-sub">Data Insight 平台 · 各模块使用方法、参数与原理</span>
      </div>
    </template>

    <div class="guide-body">
      <el-tabs v-model="activeTab" tab-position="left" class="guide-tabs">
        <el-tab-pane v-for="m in GUIDE_MODULES" :key="m.key" :name="m.key" :label="m.label">
          <template #label>
            <span class="guide-tab-label">
              <el-icon :size="16"><component :is="m.icon" /></el-icon>
              <span>{{ m.label }}</span>
            </span>
          </template>
          <div class="guide-content" v-html="renderMarkdown(GUIDE_CONTENT[m.key])"></div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { marked } from 'marked'
import { Reading } from '@element-plus/icons-vue'
import { GUIDE_MODULES, GUIDE_CONTENT } from '../guides/index.js'

const props = defineProps({
  modelValue: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue'])

// 弹窗显隐（v-model 双向绑定）
const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

// 当前激活模块（默认"平台总览"）
const activeTab = ref('overview')

// 打开时回到默认模块，保证每次打开从总览开始
watch(visible, (val) => {
  if (val) activeTab.value = 'overview'
})

// 渲染 Markdown：使用 marked 解析为 HTML；文档为平台静态内容，无外部输入，安全
function renderMarkdown(md) {
  try {
    return marked.parse(md)
  } catch {
    return '<p>文档加载失败，请刷新重试。</p>'
  }
}
</script>

<style scoped>
.guide-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.guide-header-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--text-primary);
}
.guide-header-sub {
  margin-left: 8px;
  font-size: 12px;
  color: var(--text-muted);
}

.guide-body {
  min-height: 60vh;
}
.guide-body :deep(.el-tabs__content) {
  height: 62vh;
  overflow-y: auto;
  padding: 0 8px 16px 4px;
}
/* 左侧垂直 Tab 标签：图标 + 文字 */
.guide-tab-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
}
.guide-tabs :deep(.el-tabs__item) {
  height: 44px;
  line-height: 44px;
}

/* ====== Markdown 内容样式（与数据源卡片同款浅色文档风格） ====== */
.guide-content {
  font-size: 14px;
  line-height: 1.75;
  color: var(--text-primary);
}
.guide-content :deep(h1) {
  font-size: 22px;
  font-weight: 700;
  margin: 4px 0 16px;
  padding-bottom: 10px;
  border-bottom: 2px solid var(--primary-light);
  color: var(--text-primary);
}
.guide-content :deep(h2) {
  font-size: 17px;
  font-weight: 600;
  margin: 22px 0 10px;
  padding-left: 10px;
  border-left: 3px solid var(--primary);
  color: var(--text-primary);
}
.guide-content :deep(h3) {
  font-size: 15px;
  font-weight: 600;
  margin: 16px 0 8px;
  color: var(--text-primary);
}
.guide-content :deep(h4) {
  font-size: 14px;
  font-weight: 600;
  margin: 12px 0 6px;
  color: var(--text-primary);
}
.guide-content :deep(p) {
  margin: 8px 0;
}
.guide-content :deep(ul),
.guide-content :deep(ol) {
  margin: 8px 0;
  padding-left: 24px;
}
.guide-content :deep(li) {
  margin: 4px 0;
}
.guide-content :deep(strong) {
  color: var(--text-primary);
  font-weight: 600;
}
.guide-content :deep(a) {
  color: var(--primary);
}
.guide-content :deep(blockquote) {
  margin: 10px 0;
  padding: 10px 14px;
  background: var(--primary-light);
  border-left: 3px solid var(--primary);
  border-radius: var(--radius-sm);
  color: #44507a;
  font-size: 13.5px;
}
.guide-content :deep(blockquote p) {
  margin: 0;
}
.guide-content :deep(code) {
  background: #f1f3f7;
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 12.5px;
  color: #c7254e;
  font-family: Consolas, Monaco, 'Courier New', monospace;
}
.guide-content :deep(pre) {
  background: #f8f9fc;
  border: 1px solid #e8eaef;
  border-radius: var(--radius-sm);
  padding: 12px 14px;
  overflow-x: auto;
  margin: 10px 0;
}
.guide-content :deep(pre code) {
  background: transparent;
  padding: 0;
  color: #333a4d;
  font-size: 13px;
  line-height: 1.6;
}
/* 表格 */
.guide-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 10px 0;
  font-size: 13.5px;
}
.guide-content :deep(th) {
  background: #f8fafc;
  font-weight: 600;
  text-align: left;
  color: var(--text-primary);
}
.guide-content :deep(th),
.guide-content :deep(td) {
  border: 1px solid #e5e7eb;
  padding: 8px 12px;
}
.guide-content :deep(tr:nth-child(even) td) {
  background: #fafbfc;
}
.guide-content :deep(hr) {
  border: none;
  border-top: 1px solid #e5e7eb;
  margin: 16px 0;
}
</style>
