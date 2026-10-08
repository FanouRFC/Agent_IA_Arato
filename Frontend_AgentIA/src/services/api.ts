import router from '@/router'
import { useAuthStore } from '@/stores/auth'

export async function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const auth = useAuthStore()
  const headers: Record<string, string> = { ...((opts.headers as Record<string, string>) ?? {}) }
  if (!(opts.body instanceof FormData)) headers['Content-Type'] = 'application/json'
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`
  const r = await fetch('/api' + path, { ...opts, headers })
  if (r.status === 401 && !path.startsWith('/auth')) {
    auth.logout()
    await router.push('/login')
  }
  if (!r.ok) {
    const body = await r.json().catch(() => ({ detail: r.statusText }))
    throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail))
  }
  return r.json()
}

export async function download(path: string, filename: string) {
  const auth = useAuthStore()
  const r = await fetch('/api' + path, { headers: { Authorization: `Bearer ${auth.token}` } })
  if (!r.ok) throw new Error('Téléchargement impossible')
  const url = URL.createObjectURL(await r.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: filename })
  a.click()
  URL.revokeObjectURL(url)
}

export const STATUT: Record<string, string> = {
  nouveau: 'Nouveau',
  ouvert: 'Ouvert',
  en_cours: 'En cours',
  en_attente: 'En attente',
  ferme: 'Fermé',
}
export const fmtDate = (d?: string | null) => (d ? new Date(d).toLocaleDateString('fr-FR') : '—')
export const fmtDateTime = (d?: string | null) => (d ? new Date(d).toLocaleString('fr-FR') : '—')
export const tid = (n: number) => `T-${String(n).padStart(3, '0')}`
export const SITUATION_CLASS: Record<string, string> = {
  en_retard: 'bg-brick-soft text-brick',
  a_surveiller: 'bg-ochre-soft text-ochre',
  normale: 'bg-teal-soft text-teal',
  ferme: 'bg-line/60 text-ink/70',
}
