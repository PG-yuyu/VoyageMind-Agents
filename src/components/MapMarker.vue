<template>
  <button
    class="map-marker"
    :class="[resource.place_type, { active, unverified: resource.verified === false }]"
    :style="markerStyle"
    :title="`${typeLabel}：${resource.name}`"
    @click="$emit('select', resource)"
  >
    <span>{{ typeInitial }}</span>
    <strong>{{ resource.name }}</strong>
  </button>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  resource: {
    type: Object,
    required: true
  },
  x: {
    type: Number,
    required: true
  },
  y: {
    type: Number,
    required: true
  },
  active: {
    type: Boolean,
    default: false
  }
})

defineEmits(['select'])

const typeMeta = {
  attraction: { label: '景点', initial: '景' },
  hotel: { label: '酒店', initial: '住' },
  restaurant: { label: '餐厅', initial: '食' }
}

const typeLabel = computed(() => typeMeta[props.resource.place_type]?.label || '地点')
const typeInitial = computed(() => typeMeta[props.resource.place_type]?.initial || '点')
const markerStyle = computed(() => ({
  left: `${props.x}%`,
  top: `${props.y}%`
}))
</script>

<style scoped>
.map-marker {
  position: absolute;
  z-index: 3;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  max-width: 168px;
  min-height: 36px;
  padding: 6px 10px 6px 7px;
  border: 2px solid #fff;
  border-radius: 999px;
  background: #172033;
  color: #fff;
  box-shadow: 0 14px 28px rgba(31, 41, 55, 0.2);
  transform: translate(-50%, -50%);
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}

.map-marker:hover,
.map-marker.active {
  transform: translate(-50%, -50%) scale(1.06);
  box-shadow: 0 18px 34px rgba(31, 41, 55, 0.26);
}

.map-marker span {
  display: grid;
  width: 24px;
  height: 24px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.18);
  font-size: 12px;
  font-weight: 900;
}

.map-marker strong {
  overflow: hidden;
  color: #fff;
  font-size: 12px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.map-marker.attraction {
  background: #3f5cf6;
}

.map-marker.hotel {
  background: #0f766e;
}

.map-marker.restaurant {
  background: #d97706;
}

.map-marker.unverified {
  border-color: #f59e0b;
  box-shadow: 0 0 0 5px rgba(245, 158, 11, 0.18), 0 14px 28px rgba(31, 41, 55, 0.2);
}
</style>
