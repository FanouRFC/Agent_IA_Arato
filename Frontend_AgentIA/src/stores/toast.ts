import { ref } from 'vue'
import { defineStore } from 'pinia'

export interface Toast { id: number; kind: 'ok' | 'err' | 'info'; text: string }

export const useToastStore = defineStore('toast', () => {
  const items = ref<Toast[]>([])
  let n = 0
  function push(text: string, kind: Toast['kind'] = 'info', ms = 4500) {
    const id = ++n
    items.value.push({ id, kind, text })
    setTimeout(() => dismiss(id), ms)
  }
  const dismiss = (id: number) => { items.value = items.value.filter((t) => t.id !== id) }
  return { items, push, dismiss, ok: (t: string) => push(t, 'ok'), err: (t: string) => push(t, 'err', 7000) }
})
