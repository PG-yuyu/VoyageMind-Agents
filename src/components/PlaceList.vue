<template>
  <aside class="place-list">
    <header>
      <div>
        <span>推荐资源</span>
        <strong>{{ resources.length }} 个地点</strong>
      </div>
      <small v-if="invalidCount">{{ invalidCount }} 个坐标需确认</small>
    </header>

    <nav class="place-list__tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        {{ tab.label }} {{ tab.count }}
      </button>
    </nav>

    <div class="place-list__items">
      <PlaceCard
        v-for="place in filteredResources"
        :key="place.place_id"
        :place="place"
        :active="selectedPlaceId === place.place_id"
        @select="$emit('select', place)"
      />
      <p v-if="!filteredResources.length" class="place-list__empty">当前分类暂无地点。</p>
    </div>
  </aside>
</template>

<script setup>
import { computed, ref } from 'vue'
import PlaceCard from './PlaceCard.vue'
import { needsCoordinateWarning } from '../stores/mapStore'

const props = defineProps({
  resources: {
    type: Array,
    default: () => []
  },
  selectedPlaceId: {
    type: String,
    default: ''
  }
})

defineEmits(['select'])

const activeTab = ref('all')

const invalidCount = computed(() => props.resources.filter(needsCoordinateWarning).length)
const tabs = computed(() => [
  { id: 'all', label: '全部', count: props.resources.length },
  { id: 'attraction', label: '景点', count: countByType('attraction') },
  { id: 'hotel', label: '酒店', count: countByType('hotel') },
  { id: 'restaurant', label: '餐厅', count: countByType('restaurant') },
  { id: 'invalid', label: '异常', count: invalidCount.value }
])

const filteredResources = computed(() => {
  if (activeTab.value === 'all') return props.resources
  if (activeTab.value === 'invalid') {
    return props.resources.filter(needsCoordinateWarning)
  }
  return props.resources.filter((resource) => resource.place_type === activeTab.value)
})

function countByType(type) {
  return props.resources.filter((resource) => resource.place_type === type).length
}
</script>

<style scoped>
.place-list {
  display: grid;
  align-content: start;
  gap: 14px;
  min-width: 0;
}

.place-list header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.place-list header span,
.place-list header small {
  color: #4f65ff;
  font-size: 12px;
  font-weight: 900;
}

.place-list header strong {
  display: block;
  margin-top: 5px;
  color: #101827;
  font-size: 18px;
}

.place-list header small {
  padding: 7px 9px;
  border-radius: 999px;
  background: #fff4df;
  color: #b45309;
}

.place-list__tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.place-list__tabs button {
  min-height: 34px;
  padding: 0 10px;
  border: 1px solid #d9e3ee;
  border-radius: 999px;
  background: #fff;
  color: #647286;
  font-size: 12px;
  font-weight: 900;
}

.place-list__tabs button.active {
  border-color: #172033;
  background: #172033;
  color: #fff;
}

.place-list__items {
  display: grid;
  max-height: 620px;
  gap: 12px;
  overflow: auto;
  padding-right: 4px;
}

.place-list__empty {
  margin: 0;
  padding: 18px;
  border-radius: 18px;
  background: #f7faff;
  color: #667386;
}
</style>
