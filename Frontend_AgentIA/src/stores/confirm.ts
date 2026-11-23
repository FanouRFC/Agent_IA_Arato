import { ref } from 'vue'
import { defineStore } from 'pinia'

export interface ConfirmOptions { title: string; message?: string; confirmLabel?: string; cancelLabel?: string }

/** Boîte de confirmation globale : `if (!(await confirmer.ask({ title: '…' }))) return`. */
export const useConfirmStore = defineStore('confirm', () => {
  const current = ref<(ConfirmOptions & { open: boolean }) | null>(null)
  let resolver: ((v: boolean) => void) | null = null
  function ask(o: ConfirmOptions): Promise<boolean> {
    resolver?.(false)
    current.value = { ...o, open: true }
    return new Promise<boolean>((res) => { resolver = res })
  }
  function answer(v: boolean) {
    if (current.value) current.value.open = false
    resolver?.(v); resolver = null
  }
  return { current, ask, answer }
})
