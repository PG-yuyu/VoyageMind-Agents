<template>
  <svg v-if="polylinePoints" class="route-polyline" viewBox="0 0 100 100" preserveAspectRatio="none">
    <polyline :points="polylinePoints" />
  </svg>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  points: {
    type: Array,
    default: () => []
  }
})

const polylinePoints = computed(() => {
  if (props.points.length < 2) return ''
  return props.points.map((point) => `${point.x},${point.y}`).join(' ')
})
</script>

<style scoped>
.route-polyline {
  position: absolute;
  inset: 0;
  z-index: 1;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.route-polyline polyline {
  fill: none;
  stroke: rgba(79, 101, 255, 0.72);
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.45;
}
</style>
