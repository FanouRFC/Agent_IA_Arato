<script setup lang="ts">
import { SITUATION_BADGE } from '@/services/api'
import Icon from '@/components/Icon.vue'
defineProps<{ situation: string; label: string }>()
</script>
<template>
  <span :class="SITUATION_BADGE[situation] ?? 'badge-slate'">
    <Icon v-if="situation === 'en_retard'" name="alert" :size="12" />
    <Icon v-else-if="situation === 'a_surveiller'" name="clock" :size="12" />
    {{ label }}
  </span>
</template>
