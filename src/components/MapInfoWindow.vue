<template>
  <article class="map-info-window" :style="windowStyle">
    <span>{{ typeLabel }}</span>
    <strong>{{ resource.name }}</strong>
    <p>{{ resource.recommend_reason || resource.short_description }}</p>
    <small>{{ resource.address }}</small>
  </article>
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
  }
})

const typeLabels = {
  attraction: '景点推荐',
  hotel: '住宿推荐',
  restaurant: '餐饮推荐'
}

const typeLabel = computed(() => typeLabels[props.resource.place_type] || '推荐地点')
const windowStyle = computed(() => {
  const left = Math.min(78, Math.max(22, props.x))
  const top = props.y > 58 ? props.y - 20 : props.y + 11
  return {
    left: `${left}%`,
    top: `${top}%`
  }
})
</script>

<style scoped>
.map-info-window {
  position: absolute;
  z-index: 4;
  display: grid;
  width: min(280px, 62%);
  gap: 6px;
  padding: 13px 14px;
  border: 1px solid rgba(218, 228, 238, 0.95);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 22px 48px rgba(31, 41, 55, 0.16);
  transform: translate(-50%, 0);
}

.map-info-window span {
  color: #4f65ff;
  font-size: 12px;
  font-weight: 900;
}

.map-info-window strong {
  color: #101827;
  font-size: 16px;
}

.map-info-window p,
.map-info-window small {
  margin: 0;
  color: #647286;
  line-height: 1.55;
}

.map-info-window small {
  font-size: 12px;
}
</style>
