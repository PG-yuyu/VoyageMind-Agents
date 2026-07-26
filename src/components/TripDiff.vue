<template>
  <div class="trip-diff">
    <h3 class="diff-title">修改前后对比</h3>

    <!-- 加载状态 -->
    <div v-if="loading" class="diff-loading">对比中...</div>

    <!-- 空状态 -->
    <div v-else-if="!diff" class="diff-empty">暂无对比数据</div>

    <!-- 对比内容 -->
    <div v-else class="diff-content">
      <!-- 版本信息 -->
      <div class="version-info">
        <span class="version-badge old">v{{ diff.from_version }}</span>
        <span class="version-arrow">→</span>
        <span class="version-badge new">v{{ diff.to_version }}</span>
      </div>

      <!-- 变更摘要 -->
      <div class="diff-summary">
        <div class="summary-card">
          <div class="summary-label">受影响天数</div>
          <div class="summary-value">{{ diff.affected_days.length }} 天</div>
        </div>
        <div class="summary-card">
          <div class="summary-label">变更项数</div>
          <div class="summary-value">{{ diff.changes.length }} 项</div>
        </div>
        <div class="summary-card">
          <div class="summary-label">未变更项</div>
          <div class="summary-value">{{ diff.unchanged_item_ids.length }} 项</div>
        </div>
      </div>

      <!-- 变更列表 -->
      <div class="changes-section">
        <h4 class="section-title">详细变更</h4>
        <div
          v-for="change in diff.changes"
          :key="change.before_item_id || change.after_item_id"
          class="change-item"
          :class="change.change_type"
        >
          <div class="change-type-badge">{{ changeTypeLabel(change.change_type) }}</div>

          <div class="change-detail">
            <div class="change-reason">{{ change.reason }}</div>

            <div class="change-places">
              <template v-if="change.before_place_id">
                <span class="place-badge old">{{ change.before_place_id }}</span>
                <span v-if="change.after_place_id" class="change-arrow">→</span>
              </template>
              <template v-if="change.after_place_id && change.change_type !== 'replace'">
                <span class="place-badge new">{{ change.after_place_id }}</span>
              </template>
            </div>

            <div class="change-impact">
              <span v-if="change.cost_change !== 0" class="impact-cost">
                费用: {{ formatCost(change.cost_change) }}
              </span>
              <span v-if="change.distance_change_m !== 0" class="impact-distance">
                距离: {{ formatDistance(change.distance_change_m) }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { TripDiff } from '../types/common'

defineProps<{
  diff?: TripDiff | null
  loading?: boolean
}>()

function changeTypeLabel(type: string): string {
  const map: Record<string, string> = {
    replace: '替换',
    delete: '删除',
    add: '新增',
    reorder: '重排',
  }
  return map[type] || type
}

function formatCost(change: number): string {
  const prefix = change > 0 ? '+' : ''
  return `${prefix}¥${change.toFixed(0)}`
}

function formatDistance(meters: number): string {
  const prefix = meters > 0 ? '+' : ''
  return `${prefix}${meters} m`
}
</script>

<style scoped>
.trip-diff {
  padding: 16px;
  background: #fff;
  border-radius: 8px;
}

.diff-title {
  margin: 0 0 16px;
  font-size: 18px;
  font-weight: 600;
}

.diff-loading,
.diff-empty {
  padding: 32px;
  text-align: center;
  color: #999;
}

.version-info {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-bottom: 16px;
}

.version-badge {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 14px;
  font-weight: 600;
}

.version-badge.old {
  background: #f0f0f0;
  color: #666;
}

.version-badge.new {
  background: #e6f7ff;
  color: #1890ff;
}

.version-arrow {
  font-size: 18px;
  color: #999;
}

.diff-summary {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.summary-card {
  flex: 1;
  padding: 12px;
  background: #fafafa;
  border-radius: 8px;
  text-align: center;
}

.summary-label {
  font-size: 12px;
  color: #999;
  margin-bottom: 4px;
}

.summary-value {
  font-size: 20px;
  font-weight: 700;
  color: #333;
}

.section-title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 500;
}

.changes-section {
  margin-top: 8px;
}

.change-item {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  margin-bottom: 8px;
  background: #fafafa;
  border-radius: 6px;
  border-left: 3px solid;
}

.change-item.replace { border-color: #1890ff; }
.change-item.delete { border-color: #ff4d4f; }
.change-item.add { border-color: #52c41a; }
.change-item.reorder { border-color: #faad14; }

.change-type-badge {
  width: 40px;
  height: 24px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.change-item.replace .change-type-badge { background: #e6f7ff; color: #1890ff; }
.change-item.delete .change-type-badge { background: #fff2f0; color: #ff4d4f; }
.change-item.add .change-type-badge { background: #f6ffed; color: #52c41a; }
.change-item.reorder .change-type-badge { background: #fffbe6; color: #faad14; }

.change-detail {
  flex: 1;
  font-size: 13px;
  line-height: 1.5;
}

.change-reason {
  font-weight: 500;
  margin-bottom: 4px;
}

.change-places {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.place-badge {
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
  font-family: monospace;
}

.place-badge.old { background: #f0f0f0; color: #666; }
.place-badge.new { background: #e6f7ff; color: #1890ff; }

.change-arrow {
  color: #999;
}

.change-impact {
  display: flex;
  gap: 8px;
  font-size: 12px;
}

.impact-cost,
.impact-distance {
  padding: 1px 6px;
  background: #fff;
  border: 1px solid #f0f0f0;
  border-radius: 4px;
  color: #666;
}
</style>
