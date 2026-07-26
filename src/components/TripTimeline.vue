<template>
  <div class="trip-timeline">
    <h3 class="timeline-title">行程时间轴</h3>

    <!-- 加载状态 -->
    <div v-if="loading" class="timeline-loading">加载中...</div>

    <!-- 空状态 -->
    <div v-else-if="!store.hasItinerary" class="timeline-empty">
      暂无行程数据，请先生成行程
    </div>

    <!-- 时间轴内容 -->
    <div v-else class="timeline-content">
      <div
        v-for="day in store.itinerary!.days"
        :key="day.day"
        class="day-section"
      >
        <div class="day-header">
          <span class="day-label">第 {{ day.day }} 天</span>
          <span class="day-date">{{ day.date }}</span>
          <span class="day-stats">
            步行 {{ formatDistance(day.walking_distance_m) }} |
            费用 ¥{{ day.daily_cost.toFixed(0) }}
          </span>
        </div>

        <div class="day-items">
          <div
            v-for="item in day.items"
            :key="item.item_id"
            class="timeline-item"
            :class="[item.item_type, { locked: item.locked }]"
          >
            <!-- 时间 -->
            <div class="item-time">
              <div class="time-start">{{ item.start_time }}</div>
              <div class="time-line">
                <div class="time-dot" :class="item.item_type"></div>
                <div class="time-bar"></div>
              </div>
              <div class="time-end">{{ item.end_time }}</div>
            </div>

            <!-- 内容 -->
            <div class="item-content">
              <div class="item-type-badge">{{ typeLabel(item.item_type) }}</div>
              <div class="item-place">{{ item.note || item.place_id || '未指定' }}</div>
              <div v-if="item.duration_minutes" class="item-duration">
                {{ item.duration_minutes }} 分钟
              </div>
              <div v-if="item.total_cost" class="item-cost">
                ¥{{ item.total_cost }}
              </div>
            </div>

            <!-- 锁定标记 -->
            <div v-if="item.locked" class="item-locked-badge" title="已锁定">🔒</div>
          </div>
        </div>

        <!-- 步行距离警告 -->
        <div
          v-if="day.walking_distance_m > 8000"
          class="walking-warning"
        >
          ⚠️ 当日步行 {{ formatDistance(day.walking_distance_m) }}，建议控制步行量
        </div>
      </div>

      <!-- 行程摘要 -->
      <div class="timeline-summary">
        <div class="summary-row">
          <span>总费用</span>
          <span class="summary-value">¥{{ store.totalCost.toFixed(0) }}</span>
        </div>
        <div class="summary-row">
          <span>行程天数</span>
          <span class="summary-value">{{ store.totalDays }} 天</span>
        </div>
        <div class="summary-row">
          <span>版本</span>
          <span class="summary-value">v{{ store.currentVersion }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useItineraryStore } from '../stores/itineraryStore'

const store = useItineraryStore()
const props = withDefaults(defineProps<{ loading?: boolean }>(), {
  loading: false,
})

/** 行程类型标签映射 */
function typeLabel(type: string): string {
  const map: Record<string, string> = {
    departure: '出发',
    transport: '交通',
    attraction: '景点',
    lunch: '午餐',
    dinner: '晚餐',
    hotel: '酒店',
    rest: '休息',
    return: '返回',
  }
  return map[type] || type
}

/** 格式化距离 */
function formatDistance(meters: number): string {
  if (meters >= 1000) {
    return `${(meters / 1000).toFixed(1)} km`
  }
  return `${meters} m`
}
</script>

<style scoped>
.trip-timeline {
  padding: 16px;
  background: #fff;
  border-radius: 8px;
}

.timeline-title {
  margin: 0 0 16px;
  font-size: 18px;
  font-weight: 600;
}

.timeline-empty,
.timeline-loading {
  padding: 32px;
  text-align: center;
  color: #999;
}

.day-section {
  margin-bottom: 24px;
  border: 1px solid #eee;
  border-radius: 8px;
  overflow: hidden;
}

.day-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #f8f9fa;
  font-size: 14px;
}

.day-label {
  font-weight: 600;
  color: #1890ff;
}

.day-date {
  color: #666;
}

.day-stats {
  margin-left: auto;
  color: #666;
  font-size: 13px;
}

.day-items {
  padding: 8px 16px;
}

.timeline-item {
  display: flex;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid #f0f0f0;
  position: relative;
}

.timeline-item:last-child {
  border-bottom: none;
}

.timeline-item.locked {
  opacity: 0.7;
  background: #fafafa;
}

.item-time {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 60px;
  font-size: 12px;
  color: #666;
}

.time-line {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 2px 0;
}

.time-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #d9d9d9;
}

.time-dot.attraction { background: #1890ff; }
.time-dot.lunch,
.time-dot.dinner { background: #52c41a; }
.time-dot.hotel { background: #faad14; }
.time-dot.departure,
.time-dot.return { background: #999; }

.time-bar {
  width: 2px;
  height: 100%;
  background: #e8e8e8;
}

.item-content {
  flex: 1;
  font-size: 14px;
}

.item-type-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  background: #f0f0f0;
  color: #666;
  margin-bottom: 4px;
}

.item-place {
  font-weight: 500;
  margin-bottom: 2px;
}

.item-duration,
.item-cost {
  font-size: 12px;
  color: #888;
}

.item-locked-badge {
  position: absolute;
  right: 0;
  top: 8px;
  font-size: 14px;
}

.walking-warning {
  padding: 8px 16px;
  background: #fff7e6;
  border-top: 1px solid #ffd591;
  font-size: 13px;
  color: #d46b08;
}

.timeline-summary {
  display: flex;
  justify-content: space-around;
  padding: 16px;
  background: #fafafa;
  border-radius: 8px;
  margin-top: 16px;
}

.summary-row {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #666;
}

.summary-value {
  font-size: 18px;
  font-weight: 600;
  color: #333;
}
</style>
