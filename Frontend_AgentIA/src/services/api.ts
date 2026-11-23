import router from '@/router'
import { useAuthStore } from '@/stores/auth'

/** Appel de l'API du backend (/api → FastAPI). Gère le jeton, la session expirée et des messages d'erreur lisibles. */
export async function api<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const auth = useAuthStore()
  const headers: Record<string, string> = { ...((opts.headers as Record<string, string>) ?? {}) }
  if (!(opts.body instanceof FormData)) headers['Content-Type'] = 'application/json'
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`
  let r: Response
  try {
    r = await fetch('/api' + path, { ...opts, headers })
  } catch {
    throw new Error("Le backend ne répond pas. Vérifiez que « lancer_backend.bat » est démarré.")
  }
  if (r.status === 401 && !path.startsWith('/auth')) {
    auth.logout()
    await router.push('/login')
  }
  if (!r.ok) {
    const body = await r.json().catch(() => ({ detail: r.statusText }))
    const d = body.detail
    throw new Error(typeof d === 'string' ? d : Array.isArray(d) ? d.map((x: any) => x.msg).join(' ; ') : JSON.stringify(d))
  }
  return r.json()
}

export const post = <T = any>(path: string, body?: unknown) =>
  api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
export const put = <T = any>(path: string, body: unknown) => api<T>(path, { method: 'PUT', body: JSON.stringify(body) })

export async function download(path: string, filename: string) {
  const auth = useAuthStore()
  let r: Response
  try { r = await fetch('/api' + path, { headers: { Authorization: `Bearer ${auth.token}` } }) }
  catch { throw new Error("Le backend ne répond pas. Vérifiez que « lancer_backend.bat » est démarré.") }
  if (r.status === 401) { auth.logout(); await router.push('/login'); throw new Error('Session expirée : reconnectez-vous.') }
  if (!r.ok) {
    // Le serveur explique la cause (ex. « Génération du rapport impossible : … ») : on l'affiche telle quelle.
    const detail = (await r.json().catch(() => null))?.detail
    throw new Error(typeof detail === 'string' ? detail : `Téléchargement impossible (erreur ${r.status})`)
  }
  const blob = await r.blob()
  if (!blob.size) throw new Error('Le rapport généré est vide, réessayez.')
  const url = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href: url, download: filename.replace(/[\\/:*?"<>|]+/g, '_') })
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10000)   // on laisse au navigateur le temps de lire le fichier
}

/** Rapport PDF / Excel : le serveur génère le fichier (les erreurs s'affichent telles quelles), puis le navigateur le télécharge
 *  lui-même depuis un lien tout prêt (aucun transfert par script : rien à bloquer, rien à reconstituer). */
export async function telechargerRapport(pid: number, fmt: 'pdf' | 'xlsx', filename: string) {
  const { url } = await post<{ url: string }>(`/projets/${pid}/rapports/${fmt}/lien`, {})
  const a = Object.assign(document.createElement('a'), { href: url, download: filename.replace(/[\\/:*?"<>|]+/g, '_') })
  document.body.appendChild(a); a.click(); a.remove()
}

/** API du CRM (simulateur de démonstration uniquement). */
export async function crmApi<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  let r: Response
  try {
    const headers: Record<string, string> = opts.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }
    r = await fetch('/crm-api' + path, { ...opts, headers })
  } catch {
    throw new Error("Le CRM ne répond pas. Vérifiez que « lancer_crm.bat » est démarré.")
  }
  if (!r.ok) {
    const body = await r.json().catch(() => ({ detail: r.statusText }))
    throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail))
  }
  return r.json()
}

// ---------- Libellés et styles partagés ----------
export const STATUT: Record<string, string> = {
  nouveau: 'Nouveau', ouvert: 'Ouvert', en_cours: 'En cours', en_attente: 'En attente', ferme: 'Fermé',
}
export const STATUT_BADGE: Record<string, string> = {
  nouveau: 'badge-slate', ouvert: 'badge-blue', en_cours: 'badge-blue', en_attente: 'badge-amber', ferme: 'badge-green',
}
export const SITUATION_BADGE: Record<string, string> = {
  en_retard: 'badge-red', a_surveiller: 'badge-amber', normale: 'badge-slate', ferme: 'badge-green',
}
export const RISQUE: Record<string, { label: string; cls: string }> = {
  eleve: { label: 'Risque élevé', cls: 'badge-red' },
  modere: { label: 'Risque modéré', cls: 'badge-amber' },
  faible: { label: 'Risque faible', cls: 'badge-green' },
}
export const DIAGNOSTIC: Record<string, string> = {
  historique: 'Historique', impact_systemique: 'Impact systémique', manque_de_visibilite: 'Manque de visibilité',
}
/** Adresses des photos de profil : membres du CRM (/crm-api) et comptes responsables (/api). */
export const photoCrm = (p?: string | null) => (p ? '/crm-api' + p : null)
export const photoCompte = (p?: string | null) => (p ? '/api' + p : null)
/** Nom lisible tiré d'une adresse e-mail : « jean.rakoto@arato.mg » → « Jean Rakoto ». */
export const nomAffiche = (email: string) =>
  (email.split('@')[0] ?? '').split(/[._-]+/).filter(Boolean).map((x) => x.charAt(0).toUpperCase() + x.slice(1)).join(' ') || email
export const fmtDate = (d?: string | null) => (d ? new Date(d).toLocaleDateString('fr-FR') : '—')
export const fmtDateTime = (d?: string | null) =>
  d ? new Date(d).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : '—'
export const tid = (n: number) => `T-${String(n).padStart(3, '0')}`
export const initiales = (nom: string) =>
  nom.includes('@') ? (nom.split('@')[0] ?? '').replace(/[^a-zA-Z0-9]/g, '').slice(0, 2).toUpperCase()
    : nom.split(/\s+/).map((x) => x[0] ?? '').slice(0, 2).join('').toUpperCase()
export function ilYa(d?: string | null): string {
  if (!d) return '—'
  const s = Math.max(0, Math.round((Date.now() - new Date(d).getTime()) / 1000))
  if (s < 60) return "à l'instant"
  if (s < 3600) return `il y a ${Math.floor(s / 60)} min`
  if (s < 86400) return `il y a ${Math.floor(s / 3600)} h`
  return `il y a ${Math.floor(s / 86400)} j`
}
