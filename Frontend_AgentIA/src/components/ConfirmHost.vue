<script setup lang="ts">
import { useConfirmStore } from '@/stores/confirm'
import ConfirmModal from '@/components/ConfirmModal.vue'
const c = useConfirmStore()
</script>
<template>
  <ConfirmModal :open="!!c.current?.open" :title="c.current?.title ?? ''" :confirm-label="c.current?.confirmLabel" @confirm="c.answer(true)" @cancel="c.answer(false)">
    <p v-if="c.current?.message">{{ c.current.message }}</p>
  </ConfirmModal>
</template>
