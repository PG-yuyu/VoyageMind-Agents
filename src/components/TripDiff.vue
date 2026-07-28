<template>
  <div class="trip-diff">
    <header class="diff-head">
      <div>
        <h3 class="diff-title">修改前后对比</h3>
        <p v-if="diff && hasRealChanges" class="diff-subtitle">
          {{ affectedDaysText }}，{{ diff.changes.length }} 项调整
        </p>
        <p v-else-if="diff" class="diff-subtitle">应用调整后，这里会显示最终采用的变更。</p>
      </div>
      <span v-if="diff && hasRealChanges" class="diff-version">v{{ diff.from_version }} -> v{{ diff.to_version }}</span>
    </header>

    <div v-if="loading" class="diff-loading">正在整理修改内容...</div>
    <div v-else-if="!diff" class="diff-empty">暂无对比数据</div>

    <div v-else-if="!hasRealChanges" class="diff-standby">
      <span class="standby-mark">待应用</span>
      <strong>还没有产生行程变更</strong>
      <p>先生成调整建议，确认后点击应用，这里会显示改了哪一天、哪些地点以及费用变化。</p>
    </div>

    <div v-else class="diff-content">
      <div class="diff-summary">
        <div class="summary-card">
          <span>影响天数</span>
          <strong>{{ diff.affected_days.length || 0 }} 天</strong>
        </div>
        <div class="summary-card">
          <span>已调整</span>
          <strong>{{ diff.changes.length }} 项</strong>
        </div>
        <div class="summary-card">
          <span>保持不变</span>
          <strong>{{ diff.unchanged_item_ids.length }} 项</strong>
        </div>
      </div>

      <section class="changes-section">
        <h4 class="section-title">详细变更</h4>
        <article
          v-for="(change, index) in visibleChanges"
          :key="change.before_item_id || change.after_item_id || index"
          class="change-item"
          :class="change.change_type"
        >
          <div class="change-top">
            <span class="change-type-badge">{{ changeTypeLabel(change.change_type) }}</span>
            <strong>{{ changeTitle(change) }}</strong>
          </div>
          <p class="change-route">{{ changeRouteText(change) }}</p>
          <p v-if="change.reason" class="change-reason">{{ cleanText(change.reason) }}</p>
          <div v-if="hasImpact(change)" class="change-impact">
            <span v-if="change.cost_change !== 0">费用 {{ formatCost(change.cost_change) }}</span>
            <span v-if="change.distance_change_m !== 0">距离 {{ formatDistance(change.distance_change_m) }}</span>
          </div>
        </article>

        <p v-if="!visibleChanges.length" class="diff-empty compact">暂无具体变更项</p>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { TripDiff } from '../types/common'

const props = defineProps<{
  diff?: TripDiff | null
  loading?: boolean
}>()

const hasRealChanges = computed(() => !!props.diff?.changes?.length)
const visibleChanges = computed(() => props.diff?.changes?.slice(0, 3) ?? [])

const affectedDaysText = computed(() => {
  const days = props.diff?.affected_days ?? []
  if (!days.length) return '暂未标记影响日期'
  return `影响第 ${days.join('、')} 天`
})

function changeTypeLabel(type: string): string {
  const map: Record<string, string> = {
    replace: '替换',
    delete: '移除',
    add: '新增',
    reorder: '调整',
  }
  return map[type] || '调整'
}

function changeTitle(change: TripDiff['changes'][number]): string {
  const before = displayPlace(change, 'before')
  const after = displayPlace(change, 'after')
  if (change.change_type === 'replace' && before && after) return `${before} 换成 ${after}`
  if (change.change_type === 'add' && after) return `新增 ${after}`
  if (change.change_type === 'delete' && before) return `移除 ${before}`
  if (change.change_type === 'reorder') return '调整游览顺序'
  return changeTypeLabel(change.change_type) + '行程'
}

function changeRouteText(change: TripDiff['changes'][number]): string {
  const before = displayPlace(change, 'before')
  const after = displayPlace(change, 'after')

  if (change.change_type === 'replace') {
    if (before && after) return `${before} -> ${after}`
    return readableReason(change.reason) || '已根据调整建议替换一个行程点'
  }
  if (change.change_type === 'add') return after || readableReason(change.reason) || '新增一个行程安排'
  if (change.change_type === 'delete') return before || readableReason(change.reason) || '取消一个行程安排'
  if (change.change_type === 'reorder') return readableReason(change.reason) || '已重新安排顺序'
  return readableReason(change.reason) || [before, after].filter(Boolean).join(' -> ') || '已更新行程'
}

function displayPlace(change: TripDiff['changes'][number], side: 'before' | 'after'): string {
  const name = side === 'before' ? change.before_place_name : change.after_place_name
  const id = side === 'before' ? change.before_place_id : change.after_place_id
  return readablePlace(name) || readablePlace(id) || ''
}

function readablePlace(value?: string | null): string {
  if (!value) return ''
  const cleaned = cleanText(value)
  if (!cleaned) return ''
  if (/^[a-z]+_place_\d+$/i.test(cleaned)) return ''
  if (/^(原安排|新安排|当前行程|等待智能体建议)$/.test(cleaned)) return ''
  return cleaned
}

function readableReason(value?: string | null): string {
  const text = cleanText(value)
  if (!text || /^(地点替换|项目变更|新增项目|删除项目)$/.test(text)) return ''
  return text
}

function cleanText(value?: string | null): string {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

function hasImpact(change: TripDiff['changes'][number]): boolean {
  return change.cost_change !== 0 || change.distance_change_m !== 0
}

function formatCost(change: number): string {
  const prefix = change > 0 ? '+' : ''
  return `${prefix}¥${change.toFixed(0)}`
}

function formatDistance(meters: number): string {
  const prefix = meters > 0 ? '+' : ''
  if (Math.abs(meters) >= 1000) return `${prefix}${(meters / 1000).toFixed(1)} km`
  return `${prefix}${meters} m`
}
</script>

<style scoped>
.trip-diff {
  padding: 20px;
  border: 1px solid rgba(203, 216, 232, 0.72);
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 18px 42px rgba(31, 41, 55, 0.06);
}

.diff-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.diff-title {
  margin: 0;
  color: #111827;
  font-size: 22px;
  font-weight: 900;
}

.diff-subtitle {
  margin: 6px 0 0;
  color: #69778b;
  font-size: 13px;
  font-weight: 750;
}

.diff-version {
  flex: 0 0 auto;
  padding: 7px 12px;
  border-radius: 999px;
  background: #f3f7fc;
  color: #516175;
  font-size: 12px;
  font-weight: 900;
}

.diff-loading,
.diff-empty {
  padding: 22px;
  border: 1px dashed #d7e2ef;
  border-radius: 18px;
  background: #f8fbff;
  color: #69778b;
  text-align: center;
  font-size: 13px;
  font-weight: 800;
}

.diff-standby {
  display: grid;
  gap: 8px;
  min-height: 148px;
  align-content: center;
  padding: 24px;
  border: 1px dashed #d7e2ef;
  border-radius: 20px;
  background: linear-gradient(135deg, rgba(248, 251, 255, 0.92), rgba(239, 252, 249, 0.72));
}

.standby-mark {
  width: fit-content;
  padding: 5px 10px;
  border-radius: 999px;
  background: #ecfdf9;
  color: #0f8f83;
  font-size: 12px;
  font-weight: 900;
}

.diff-standby strong {
  color: #111827;
  font-size: 18px;
  font-weight: 950;
}

.diff-standby p {
  max-width: 360px;
  margin: 0;
  color: #69778b;
  font-size: 13px;
  font-weight: 750;
  line-height: 1.65;
}

.diff-empty.compact {
  padding: 14px;
  margin: 0;
}

.diff-content {
  display: grid;
  gap: 16px;
}

.diff-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.summary-card {
  display: grid;
  gap: 5px;
  min-height: 78px;
  align-content: center;
  padding: 12px 14px;
  border: 1px solid #dce7f2;
  border-radius: 16px;
  background: #f8fbff;
}

.summary-card span {
  color: #7a879a;
  font-size: 12px;
  font-weight: 800;
}

.summary-card strong {
  color: #172033;
  font-size: 20px;
  font-weight: 950;
}

.changes-section {
  display: grid;
  gap: 10px;
}

.section-title {
  margin: 0;
  color: #172033;
  font-size: 15px;
  font-weight: 900;
}

.change-item {
  display: grid;
  gap: 8px;
  padding: 14px;
  border: 1px solid #dce7f2;
  border-radius: 16px;
  background: #fff;
}

.change-item.replace { border-left: 4px solid #4f65ff; }
.change-item.delete { border-left: 4px solid #ef4444; }
.change-item.add { border-left: 4px solid #14b8a6; }
.change-item.reorder { border-left: 4px solid #f59e0b; }

.change-top {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.change-top strong {
  color: #111827;
  font-size: 14px;
  font-weight: 900;
  line-height: 1.45;
}

.change-type-badge {
  flex: 0 0 auto;
  padding: 4px 8px;
  border-radius: 999px;
  background: #edf4ff;
  color: #4f65ff;
  font-size: 12px;
  font-weight: 900;
}

.change-route {
  margin: 0;
  color: #172033;
  font-size: 14px;
  font-weight: 850;
  line-height: 1.45;
}

.change-reason {
  margin: 0;
  color: #69778b;
  font-size: 13px;
  line-height: 1.55;
}

.change-impact {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.change-impact span {
  padding: 5px 9px;
  border-radius: 999px;
  background: #f3f7fc;
  color: #516175;
  font-size: 12px;
  font-weight: 850;
}

@media (max-width: 760px) {
  .diff-head,
  .diff-summary {
    grid-template-columns: 1fr;
  }

  .diff-head {
    display: grid;
  }
}
</style>
