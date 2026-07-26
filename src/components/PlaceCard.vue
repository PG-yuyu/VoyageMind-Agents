<template>
  <article
    class="place-card"
    :class="[{ active, invalid: coordinateWarning }, place.place_type]"
    @click="$emit('select', place)"
  >
    <header>
      <span>{{ typeLabel }}</span>
      <strong>{{ place.name }}</strong>
    </header>

    <p>{{ place.short_description || '暂无地点摘要' }}</p>

    <div class="place-card__meta">
      <small v-if="place.price !== null && place.price !== undefined">约 {{ place.price }} 元</small>
      <small v-if="place.open_time">{{ place.open_time }}</small>
      <small>{{ place.address || '地址待补充' }}</small>
    </div>

    <div v-if="place.tags?.length" class="place-card__tags">
      <em v-for="tag in place.tags.slice(0, 4)" :key="tag">{{ tag }}</em>
    </div>

    <footer>
      <p>{{ place.recommend_reason || '推荐理由待补充' }}</p>
      <b v-if="coordinateWarning">{{ warningText }}</b>
    </footer>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { hasRenderableCoordinate, needsCoordinateWarning } from '../stores/mapStore'

const props = defineProps({
  place: {
    type: Object,
    required: true
  },
  active: {
    type: Boolean,
    default: false
  }
})

defineEmits(['select'])

const typeLabels = {
  attraction: '景点',
  hotel: '酒店',
  restaurant: '餐厅'
}

const typeLabel = computed(() => typeLabels[props.place.place_type] || '地点')
const canRenderMarker = computed(() => hasRenderableCoordinate(props.place))
const coordinateWarning = computed(() => needsCoordinateWarning(props.place))
const warningText = computed(() => {
  if (!canRenderMarker.value) return '坐标缺失，暂不渲染 Marker'
  if (props.place.verified === false) return props.place.warning || '坐标未验证，已用待确认 Marker 展示'
  return '坐标缺失，暂不渲染 Marker'
})
</script>

<style scoped>
.place-card {
  display: grid;
  gap: 10px;
  padding: 15px;
  border: 1px solid #e1e9f2;
  border-radius: 18px;
  background: #fff;
  text-align: left;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.place-card:hover,
.place-card.active {
  border-color: rgba(79, 101, 255, 0.52);
  box-shadow: 0 16px 34px rgba(31, 41, 55, 0.1);
  transform: translateY(-1px);
}

.place-card.invalid {
  background: #fff8f1;
}

.place-card header {
  display: grid;
  gap: 5px;
}

.place-card span {
  width: fit-content;
  padding: 5px 8px;
  border-radius: 999px;
  background: #eef3ff;
  color: #3043a4;
  font-size: 12px;
  font-weight: 900;
}

.place-card.hotel span {
  background: #e9fbf7;
  color: #0f766e;
}

.place-card.restaurant span {
  background: #fff4df;
  color: #b45309;
}

.place-card strong {
  color: #101827;
  font-size: 16px;
}

.place-card p {
  margin: 0;
  color: #647286;
  line-height: 1.6;
}

.place-card__meta,
.place-card__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.place-card__meta small,
.place-card__tags em {
  padding: 5px 8px;
  border-radius: 999px;
  background: #f4f7fb;
  color: #5b687b;
  font-size: 12px;
  font-style: normal;
  font-weight: 850;
}

.place-card footer {
  display: grid;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid #edf2f7;
}

.place-card footer p {
  color: #273244;
  font-weight: 750;
}

.place-card b {
  color: #b45309;
  font-size: 12px;
}
</style>
