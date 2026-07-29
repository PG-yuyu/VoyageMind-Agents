<template>
  <article
    class="place-card"
    :class="[{ active }, place.place_type]"
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
    </div>

    <footer>
      <p>{{ place.address || '地址待补充' }}</p>
    </footer>
  </article>
</template>

<script setup>
import { computed } from 'vue'

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
</script>

<style scoped>
.place-card {
  display: grid;
  gap: 7px;
  padding: 12px;
  border: 1px solid #e1e9f2;
  border-radius: 15px;
  background: #fbfdff;
  text-align: left;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
  cursor: pointer;
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
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
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
  overflow: hidden;
  color: #101827;
  font-size: 15px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.place-card p {
  margin: 0;
  color: #647286;
  line-height: 1.6;
}

.place-card > p,
.place-card footer p {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
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
  gap: 4px;
  padding-top: 0;
  border-top: 0;
}

.place-card footer p {
  color: #667386;
  font-size: 12px;
  font-weight: 750;
}

.place-card b {
  color: #b45309;
  font-size: 12px;
}
</style>
