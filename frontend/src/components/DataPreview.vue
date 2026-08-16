<template>
  <div class="data-preview">
    <div class="preview-head">
      <span class="preview-title">数据预览</span>
      <span v-if="total > 0" class="preview-meta">共 {{ total.toLocaleString() }} 行，显示前 {{ rows.length }} 行</span>
    </div>
    <el-table
      :data="rows"
      border
      stripe
      size="small"
      v-loading="loading"
      max-height="280"
      :empty-text="emptyText || '暂无数据'"
    >
      <el-table-column
        v-for="col in columns"
        :key="col"
        :prop="col"
        :label="col"
        min-width="110"
        show-overflow-tooltip
      />
    </el-table>
  </div>
</template>

<script setup>
defineProps({
  columns: { type: Array, default: () => [] },
  rows: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  total: { type: Number, default: 0 },
  emptyText: { type: String, default: '' }
})
</script>

<style scoped>
.data-preview {
  width: 100%;
  margin-top: 4px;
}
.preview-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.preview-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.preview-meta {
  font-size: 12px;
  color: var(--text-muted, #909399);
}
</style>
