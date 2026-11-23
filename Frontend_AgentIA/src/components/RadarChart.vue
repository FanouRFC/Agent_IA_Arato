<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

/** Radar (toile d'araignée) : un axe par critère, valeur de 0 à 1 ; null = pas encore de donnée. Sans dépendance. */
export interface Axe { label: string; value: number | null }
const props = withDefaults(defineProps<{ axes: Axe[]; size?: number }>(), { size: 340 })
const ready = ref(false)
const hover = ref<number | null>(null)
onMounted(() => requestAnimationFrame(() => (ready.value = true)))

const c = computed(() => props.size / 2)
const R = computed(() => props.size / 2 - 58)
const n = computed(() => props.axes.length)
const ang = (i: number) => -Math.PI / 2 + (2 * Math.PI * i) / n.value
const pt = (i: number, v: number) => [c.value + Math.cos(ang(i)) * R.value * v, c.value + Math.sin(ang(i)) * R.value * v]
const poly = (vals: number[]) => vals.map((v, i) => pt(i, v).join(',')).join(' ')
const anneaux = [0.25, 0.5, 0.75, 1]
const valeurs = computed(() => props.axes.map((a) => a.value ?? 0))
// Étiquette découpée en lignes de ~14 caractères pour ne jamais déborder du cadre
const lignes = (t: string) => {
  const out: string[] = []
  for (const w of t.split(' ')) {
    if (out.length && (out[out.length - 1] + ' ' + w).length <= 14) out[out.length - 1] += ' ' + w
    else out.push(w)
  }
  return out
}
const labelPos = (i: number) => {
  const [x, y] = pt(i, 1.2)
  const cos = Math.cos(ang(i))
  return { x, y, anchor: Math.abs(cos) < 0.2 ? 'middle' : cos > 0 ? 'start' : 'end' }
}
</script>

<template>
  <svg :viewBox="`-90 -10 ${size + 180} ${size + 20}`" class="mx-auto w-full max-w-[32rem]" role="img" aria-label="Profil de qualité de l'agent">
    <defs>
      <linearGradient id="radar-fill" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#4F8B89" stop-opacity=".55" /><stop offset="1" stop-color="#1B355C" stop-opacity=".55" />
      </linearGradient>
      <linearGradient id="radar-line" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4F8B89" /><stop offset="1" stop-color="#223E67" /></linearGradient>
    </defs>
    <polygon v-for="r in anneaux" :key="r" :points="poly(axes.map(() => r))" fill="none" :stroke="r === 1 ? '#CCD1D8' : '#DFE4EC'" :stroke-dasharray="r === 1 ? '' : '3 4'" />
    <line v-for="(_, i) in axes" :key="'l' + i" :x1="c" :y1="c" :x2="pt(i, 1)[0]" :y2="pt(i, 1)[1]" stroke="#DFE4EC" />
    <g :style="{ transform: ready ? 'scale(1)' : 'scale(0.05)', transformOrigin: `${c}px ${c}px`, transition: 'transform 900ms cubic-bezier(.2,.8,.2,1)' }">
      <polygon :points="poly(valeurs)" fill="url(#radar-fill)" stroke="url(#radar-line)" stroke-width="2.5" stroke-linejoin="round" />
      <circle v-for="(a, i) in axes" :key="'p' + i" :cx="pt(i, valeurs[i] ?? 0)[0]" :cy="pt(i, valeurs[i] ?? 0)[1]" :r="hover === i ? 7 : 5"
        :fill="a.value === null ? '#fff' : '#223E67'" :stroke="a.value === null ? '#CCD1D8' : '#fff'" stroke-width="2.5" class="cursor-pointer transition-all"
        @mouseenter="hover = i" @mouseleave="hover = null"><title>{{ a.label }} : {{ a.value === null ? 'pas encore de donnée' : Math.round(a.value * 100) + ' %' }}</title></circle>
    </g>
    <text v-for="(a, i) in axes" :key="'t' + i" :x="labelPos(i).x" :y="labelPos(i).y" :text-anchor="labelPos(i).anchor" dominant-baseline="middle"
      class="fill-slate-600 text-[13px] font-medium" :class="hover === i && 'fill-brand-700'">
      <tspan v-for="(l, k) in lignes(a.label)" :key="k" :x="labelPos(i).x" :dy="k === 0 ? -(lignes(a.label).length - 1) * 7 : 14">{{ l }}</tspan>
      <tspan :x="labelPos(i).x" dy="15" class="fill-slate-900 text-[14px] font-semibold">{{ a.value === null ? '—' : Math.round(a.value * 100) + ' %' }}</tspan>
    </text>
  </svg>
</template>
