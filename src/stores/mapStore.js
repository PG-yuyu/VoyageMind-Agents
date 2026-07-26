import { computed, ref } from 'vue'

export function isValidMapResource(resource) {
  return hasRenderableCoordinate(resource)
}

export function hasRenderableCoordinate(resource) {
  const longitude = Number(resource?.longitude)
  const latitude = Number(resource?.latitude)
  return (
    Number.isFinite(longitude) &&
    Number.isFinite(latitude)
  )
}

export function needsCoordinateWarning(resource) {
  return !hasRenderableCoordinate(resource) || resource?.verified === false
}

export function createMapStore(initialResources = []) {
  const resources = ref([...initialResources])
  const selectedPlaceId = ref(null)

  const validResources = computed(() => resources.value.filter(hasRenderableCoordinate))
  const invalidResources = computed(() => resources.value.filter(needsCoordinateWarning))
  const selectedResource = computed(() => {
    return resources.value.find((resource) => resource.place_id === selectedPlaceId.value) || validResources.value[0] || resources.value[0] || null
  })

  function setResources(nextResources = []) {
    resources.value = [...nextResources]
    if (!resources.value.some((resource) => resource.place_id === selectedPlaceId.value)) {
      selectedPlaceId.value = validResources.value[0]?.place_id || resources.value[0]?.place_id || null
    }
  }

  function selectPlace(placeId) {
    selectedPlaceId.value = placeId
  }

  return {
    resources,
    selectedPlaceId,
    validResources,
    invalidResources,
    selectedResource,
    setResources,
    selectPlace
  }
}
