<template>
  <aside class="place-list">
    <header>
      <div>
        <span>推荐资源</span>
        <strong>{{ resources.length }} 个地点</strong>
      </div>
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

const tabs = computed(() => [
  { id: 'all', label: '全部', count: props.resources.length },
  { id: 'attraction', label: '景点', count: countByType('attraction') },
  { id: 'hotel', label: '酒店', count: countByType('hotel') },
  { id: 'restaurant', label: '餐厅', count: countByType('restaurant') }
])

const filteredResources = computed(() => {
  if (activeTab.value === 'all') return props.resources
  return props.resources.filter((resource) => resource.place_type === activeTab.value)
})

function countByType(type) {
  return props.resources.filter((resource) => resource.place_type === type).length
}
</script>

<style scoped>
.place-list {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  align-content: start;
  gap: 10px;
  min-width: 0;
  min-height: 0;
  padding: 14px;
  border: 1px solid #dfe8f2;
  border-radius: 20px;
  background: #ffffff;
  overflow: hidden;
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
  margin-top: 3px;
  color: #101827;
  font-size: 17px;
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
  gap: 7px;
}

.place-list__tabs button {
  min-height: 30px;
  padding: 0 9px;
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
  align-content: start;
  min-height: 0;
  gap: 9px;
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
