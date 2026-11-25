<script setup lang="ts">
import { useConfirmStore } from '@/stores/confirm'
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { api, fmtDateTime, initiales, photoCompte, post, put } from "@/services/api";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toast";
import { useLlmStore } from "@/stores/llm";
import Avatar from "@/components/Avatar.vue";
import ConfirmModal from "@/components/ConfirmModal.vue";
import Icon from "@/components/Icon.vue";
import PageHeader from "@/components/PageHeader.vue";

const confirmer = useConfirmStore()
const toast = useToastStore();
const llmStore = useLlmStore();
const auth = useAuthStore();
const route = useRoute();
const tab = ref<"llm" | "journal" | "comptes">(route.query.onglet === "comptes" ? "comptes" : route.query.onglet === "journal" ? "journal" : "llm");
const TABS = [
  { k: "llm", l: "Modèle d'IA", i: "sparkles" },
  { k: "journal", l: "Journal", i: "list" },
  { k: "comptes", l: "Comptes", i: "user" },
] as const;
const journal = ref<any[]>([]),
  llm = ref<{ hote: string; local: boolean; modele: string } | null>(null),
  chargement = ref(true);

// ----- Modèle d'IA : liste des modèles disponibles + changement du modèle actif -----
const test = ref<any>(null),
  modeles = ref<string[]>([]),
  recherche = ref(""),
  testing = ref(false),
  listing = ref(false),
  activating = ref<string | null>(null),
  modelesErr = ref("");

async function lister() {
  listing.value = true;
  modelesErr.value = "";
  try {
    const r = await api("/admin/llm/modeles");
    modeles.value = r.modeles;
    if (!r.ok) modelesErr.value = r.erreur;
  } catch (e: any) {
    modelesErr.value = e.message;
  }
  listing.value = false;
}
/** Le modèle choisi devient immédiatement le modèle actif de l'agent (sans redémarrage). */
async function activer(m: string) {
  if (!llm.value || activating.value || m === llm.value.modele) return;
  if (!(await confirmer.ask({ title: 'Changer de modèle d\'IA ?', message: `Le modèle « ${m} » sera utilisé pour toutes les analyses et le chat.`, confirmLabel: 'Activer' }))) return;
  activating.value = m;
  try {
    await put("/admin/llm/modele", { modele: m });
    llm.value.modele = m;
    if (llmStore.info) llmStore.info.modele = m;   // la barre supérieure change à l'instant (pas besoin de changer de page)
    llmStore.refresh();
    test.value = null;
    toast.ok(`Modèle actif : ${m}`);
    chargerJournal();
  } catch (e: any) {
    toast.err(e.message);
  }
  activating.value = null;
}
async function tester() {
  testing.value = true;
  test.value = null;
  try {
    test.value = await post("/admin/llm/test");
  } catch (e: any) {
    test.value = { ok: false, erreur: e.message };
  }
  testing.value = false;
}
const modelesFiltres = computed(() => {
  const n = recherche.value.trim().toLowerCase();
  const actif = llm.value?.modele;
  return modeles.value
    .filter((m) => !n || m.toLowerCase().includes(n))
    .sort((x, y) => (x === actif ? -1 : y === actif ? 1 : x.localeCompare(y)));
});
const actifIndisponible = computed(
  () => !!llm.value && modeles.value.length > 0 && !modeles.value.includes(llm.value.modele),
);

// ----- Journal : une seule date, ou « 7 derniers jours » ; rien n'est affiché sans filtre -----
const jour = ref(""),
  sept = ref(false),
  erreurPeriode = ref("");
const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const aujourdhui = iso(new Date());
function jourMoins(n: number) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return iso(d);
}
const filtreActif = computed(() => !!jour.value || sept.value);
function choisirSept() {
  sept.value = !sept.value;
  if (sept.value) jour.value = "";
}
function reinitialiser() {
  jour.value = "";
  sept.value = false;
  journal.value = [];
  selection.value = new Set();
}
watch(jour, (v) => { if (v) sept.value = false; });
async function chargerJournal() {
  selection.value = new Set();
  if (!filtreActif.value) {          // aucun filtre : rien n'est affiché
    journal.value = [];
    erreurPeriode.value = "";
    return;
  }
  erreurPeriode.value = "";
  const qs = new URLSearchParams();
  if (sept.value) { qs.set("du", jourMoins(6)); qs.set("au", aujourdhui); }
  else { qs.set("du", jour.value); qs.set("au", jour.value); }
  try {
    journal.value = await api(`/admin/journal?${qs}`);
  } catch (e: any) {
    toast.err(e.message);
  }
}
watch([jour, sept], chargerJournal);

// Suppression d'entrées du journal
const selection = ref<Set<number>>(new Set()),
  confirmSuppr = ref(false),
  supprBusy = ref(false);
const tousCoches = computed(() => journal.value.length > 0 && selection.value.size === journal.value.length);
function cocher(id: number) {
  const n = new Set(selection.value);
  n.has(id) ? n.delete(id) : n.add(id);
  selection.value = n;
}
function toutCocher() {
  selection.value = tousCoches.value ? new Set() : new Set(journal.value.map((j) => j.id));
}
async function supprimerEntrees() {
  supprBusy.value = true;
  try {
    const r = await post("/admin/journal/supprimer", { ids: [...selection.value] });
    toast.ok(`${r.supprimees} entrée(s) supprimée(s).`);
    confirmSuppr.value = false;
    await chargerJournal();
  } catch (e: any) {
    toast.err(e.message);
    confirmSuppr.value = false;
  }
  supprBusy.value = false;
}

// ----- Comptes responsables -----
const comptes = ref<any[]>([]);
const photoBusy = ref(false), fichierPhoto = ref<HTMLInputElement>();
async function choisirPhoto(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  (e.target as HTMLInputElement).value = "";
  if (!f) return;
  if (!/^image\//.test(f.type)) return toast.err("Choisissez une image (PNG, JPEG, WebP ou GIF).");
  if (f.size > 5 * 1024 * 1024) return toast.err("Image trop lourde (5 Mo maximum).");
  photoBusy.value = true;
  try {
    const fd = new FormData();
    fd.append("fichier", f);
    const r = await api("/compte/photo", { method: "POST", body: fd });
    auth.photo = r.photo;
    toast.ok("Photo de profil enregistrée.");
    await chargerComptes();
  } catch (e: any) { toast.err(e.message); }
  photoBusy.value = false;
}
async function retirerPhoto() {
  if (!(await confirmer.ask({ title: 'Supprimer votre photo de profil ?', confirmLabel: 'Supprimer' }))) return;
  photoBusy.value = true;
  try {
    const r = await api("/compte/photo", { method: "DELETE" });
    auth.photo = r.photo;
    toast.ok("Photo de profil supprimée.");
    await chargerComptes();
  } catch (e: any) { toast.err(e.message); }
  photoBusy.value = false;
}
const moi = computed(() => comptes.value.find((c) => c.moi));
async function chargerComptes() {
  try {
    comptes.value = await api("/comptes");
  } catch (e: any) {
    toast.err(e.message);
  }
}
/** Active ou désactive un compte déjà accepté (compte principal uniquement). */
async function basculerCompte(c: any) {
  if (!(await confirmer.ask({
    title: c.actif ? 'Désactiver ce compte ?' : 'Réactiver ce compte ?',
    message: c.actif ? `${c.email} ne pourra plus se connecter.` : `${c.email} pourra de nouveau se connecter.`,
    confirmLabel: c.actif ? 'Désactiver' : 'Réactiver',
  }))) return;
  try {
    await put(`/comptes/${c.id}/actif`, { actif: !c.actif });
    toast.ok(c.actif ? "Compte désactivé." : "Compte réactivé.");
    await Promise.all([chargerComptes(), chargerJournal()]);
  } catch (e: any) {
    toast.err(e.message);
  }
}

// ----- Demandes d'inscription : à accepter ou refuser par le compte principal -----
const demandes = ref<any[]>([]),
  demandeBusy = ref<number | null>(null);
async function chargerDemandes() {
  if (!moi.value?.principal) { demandes.value = []; return; }
  try {
    demandes.value = await api("/comptes/demandes");
  } catch (e: any) {
    toast.err(e.message);
  }
}
async function traiterDemande(d: any, accepter: boolean) {
  if (!(await confirmer.ask({
    title: accepter ? 'Accepter cette inscription ?' : 'Refuser cette inscription ?',
    message: accepter
      ? `${d.email} pourra se connecter avec les mêmes droits que vous.`
      : `La demande de ${d.email} sera supprimée.`,
    confirmLabel: accepter ? 'Accepter' : 'Refuser',
  }))) return;
  demandeBusy.value = d.id;
  try {
    await post(`/comptes/${d.id}/${accepter ? 'accepter' : 'refuser'}`);
    toast.ok(accepter ? "Compte accepté." : "Demande refusée.");
    await chargerComptes();
    await Promise.all([chargerDemandes(), chargerJournal()]);
  } catch (e: any) {
    toast.err(e.message);
  }
  demandeBusy.value = null;
}

async function load() {
  await chargerComptes();
  chargerDemandes();
  try {
    llm.value = await api("/admin/llm");
  } catch (e: any) {
    toast.err(e.message);
  }
  chargement.value = false;
  lister();
}
/** Rend lisibles les messages techniques du journal (les textes complets restent visibles au survol). */
function lire(action: string): { texte: string; detail?: string; erreur?: boolean } {
  if (action.startsWith("Paramètres modifiés")) {
    const jours = action.match(/'seuil_jours': (\d+)/)?.[1];
    const avanc = action.match(/'seuil_avancement': (\d+)/)?.[1];
    const feries = (action.match(/\d{4}-\d{2}-\d{2}/g) ?? []).length;
    const modele = action.match(/'llm_model': '([^']*)'/)?.[1];
    if (jours && avanc && modele)
      return { texte: "Paramètres modifiés", detail: `Seuil ${jours} j · avancement ${avanc} % · ${feries} jour(s) férié(s) · modèle ${modele}` };
  }
  const mail = action.match(/^E-mail d'affectation non envoyé à (\S+) : (.*)$/s);
  if (mail) return { texte: `E-mail non envoyé à ${mail[1]}`, detail: mail[2], erreur: true };
  const ok = action.match(/^E-mail d'affectation envoyé à (\S+)(?: \((.*)\))?$/s);
  if (ok) return { texte: `E-mail envoyé à ${ok[1]}`, detail: ok[2] === "test" ? "E-mail de test" : ok[2] ? `Ticket ${ok[2]}` : undefined };
  return { texte: action };
}
const lignes = computed(() => journal.value.map((j) => ({ ...j, ...lire(j.action) })));


watch(() => route.query.onglet, (o) => { if (o === "comptes") tab.value = "comptes"; });
onMounted(load);
</script>

<template>
  <div class="mx-auto max-w-6xl">
    <PageHeader
      title="Administration"
      subtitle="Réglages généraux de toute l'application : modèle d'IA, journal et comptes."
    />

    <!-- Onglets -->
    <div
      class="mb-6 inline-flex rounded-xl bg-slate-100 p-1"
      role="tablist"
      aria-label="Sections d'administration"
    >
      <button
        v-for="t in TABS"
        :key="t.k"
        role="tab"
        :aria-selected="tab === t.k"
        class="inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition focus-visible:outline-2 focus-visible:outline-brand-600 cursor-pointer"
        :class="
          tab === t.k
            ? 'bg-white text-slate-900 shadow-sm'
            : 'text-slate-500 hover:text-slate-800'
        "
        @click="tab = t.k"
      >
        <Icon :name="t.i" :size="15" />{{ t.l }}
        <span
          v-if="t.k === 'comptes' && demandes.length"
          class="badge-blue"
          :aria-label="`${demandes.length} demande(s) d'inscription`"
        >{{ demandes.length }}</span>
      </button>
    </div>

    <!-- Chargement -->
    <div v-if="chargement" class="card card-pad flex items-center gap-3" role="status" aria-live="polite">
      <Icon name="refresh" :size="18" class="animate-spin text-brand-600" />
      <p class="muted">Chargement de l'administration…</p>
    </div>

    <template v-else>
      <!-- Modèle d'IA -->
      <section v-show="tab === 'llm'" class="space-y-4">
        <div v-if="llm" class="card">
          <header class="flex flex-wrap items-center gap-4 border-b border-line px-6 py-5">
            <span class="grid size-11 place-items-center rounded-xl bg-brand-50 text-brand-600"
              ><Icon :name="llm.local ? 'server' : 'cloud'" :size="22"
            /></span>
            <div class="min-w-0 flex-1">
              <h2 class="card-title">Modèle d'IA en ligne</h2>
              <p class="muted mt-0.5">
                Fournisseur : <b class="font-semibold text-slate-700">{{ llm.hote }}</b>
              </p>
            </div>
            <div class="text-right">
              <p class="eyebrow">Modèle actif</p>
              <p class="mt-0.5 inline-flex items-center gap-2 text-sm font-semibold text-slate-900">
                <span class="live-dot size-2 rounded-full bg-emerald-500" />{{ llm.modele }}
              </p>
            </div>
          </header>

          <div class="space-y-5 p-6">
            <p
              v-if="actifIndisponible"
              class="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
              role="alert"
            >
              <Icon name="alert" :size="16" class="mt-0.5 shrink-0" />
              Le modèle actif n'est pas proposé par ce fournisseur : choisissez-en un dans la liste ci-dessous.
            </p>

            <!-- Liste des modèles -->
            <div>
              <div class="flex flex-wrap items-center gap-2">
                <h3 class="text-sm font-semibold text-slate-900">Modèles disponibles</h3>
                <span v-if="modeles.length" class="badge-slate">{{ modeles.length }}</span>
                <button class="btn-secondary btn-sm ml-auto" :disabled="listing" @click="lister">
                  <Icon name="refresh" :size="13" :class="listing && 'animate-spin'" />
                  {{ listing ? "Chargement…" : "Actualiser la liste" }}
                </button>
              </div>

              <div v-if="modeles.length > 8" class="relative mt-3">
                <Icon name="search" :size="15" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input v-model="recherche" class="input pl-9" placeholder="Filtrer les modèles" aria-label="Filtrer les modèles" />
              </div>

              <p v-if="modelesErr" class="mt-3 flex items-center gap-1.5 text-sm text-red-600" role="alert">
                <Icon name="alert" :size="14" />{{ modelesErr }}
              </p>
              <p v-else-if="listing && !modeles.length" class="mt-3 text-sm text-slate-500">Recherche des modèles disponibles…</p>

              <ul
                v-if="modelesFiltres.length"
                class="mt-3 max-h-80 divide-y divide-slate-100 overflow-y-auto rounded-xl border border-line"
                role="radiogroup"
                aria-label="Modèles disponibles"
              >
                <li v-for="m in modelesFiltres" :key="m">
                  <button
                    type="button"
                    role="radio"
                    :aria-checked="m === llm.modele"
                    class="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm transition hover:bg-slate-50 disabled:cursor-default"
                    :class="m === llm.modele ? 'bg-brand-50/60' : ''"
                    :disabled="!!activating || m === llm.modele"
                    @click="activer(m)"
                  >
                    <span
                      class="grid size-4 shrink-0 place-items-center rounded-full border"
                      :class="m === llm.modele ? 'border-brand-600 bg-brand-600 text-white' : 'border-slate-300'"
                    >
                      <Icon v-if="m === llm.modele" name="check" :size="10" />
                    </span>
                    <span class="min-w-0 flex-1 truncate font-medium" :class="m === llm.modele ? 'text-slate-900' : 'text-slate-700'">{{ m }}</span>
                    <span v-if="m === llm.modele" class="badge-blue">Actif</span>
                    <span v-else-if="activating === m" class="text-xs text-slate-500">Activation…</span>
                    <span v-else class="text-xs font-medium text-brand-700">Activer</span>
                  </button>
                </li>
              </ul>
              <p v-else-if="modeles.length" class="mt-3 text-sm text-slate-500">Aucun modèle ne correspond à « {{ recherche }} ».</p>
            </div>

            <div class="flex flex-wrap items-center gap-4 border-t border-slate-100 pt-5">
              <button class="btn-primary" :disabled="testing" @click="tester">
                <Icon :name="testing ? 'refresh' : 'activity'" :size="16" :class="testing && 'animate-spin'" />
                {{ testing ? "Test en cours…" : "Tester la connexion" }}
              </button>
              <p
                v-if="test?.ok"
                class="inline-flex items-center gap-2 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
                role="status"
              >
                <Icon name="check" :size="16" />Connexion réussie · {{ test.modele }} · {{ test.latence_ms }} ms
              </p>
              <p
                v-else-if="test"
                class="inline-flex items-center gap-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800"
                role="alert"
              >
                <Icon name="alert" :size="16" />{{ test.erreur }}
              </p>
            </div>
          </div>
        </div>
        <div v-else class="card card-pad text-sm text-slate-500">
          Impossible de lire la configuration du modèle d'IA.
        </div>
      </section>

      <!-- Journal -->
      <section v-show="tab === 'journal'" class="card">
        <header class="flex flex-wrap items-center gap-2 border-b border-line px-6 py-4">
          <h2 class="card-title">Journal général</h2>
          <span v-if="filtreActif" class="badge-slate ml-auto">{{ journal.length }} entrée(s)</span>
        </header>

        <!-- Filtre : une date précise ou les 7 derniers jours -->
        <div class="flex flex-wrap items-end gap-x-4 gap-y-3 border-b border-line bg-slate-50/60 px-6 py-3.5">
          <div>
            <label class="label" for="j-date">Date</label>
            <input id="j-date" v-model="jour" type="date" class="input w-auto!" :max="aujourdhui" />
          </div>
          <div class="flex flex-wrap items-center gap-1.5 pb-0.5">
            <button
              type="button"
              class="rounded-full border px-3 py-1 text-xs font-medium transition"
              :class="sept ? 'border-brand-600 bg-brand-600 text-white' : 'border-line bg-white text-slate-600 hover:border-brand-300 hover:bg-brand-50'"
              @click="choisirSept"
            >7 derniers jours</button>
            <button v-if="filtreActif" type="button" class="btn-ghost btn-sm" @click="reinitialiser">
              <Icon name="x" :size="13" />Réinitialiser
            </button>
          </div>
          <div v-if="journal.length" class="ml-auto flex flex-wrap items-center gap-3 pb-0.5">
            <label class="flex cursor-pointer items-center gap-2 text-xs text-slate-600">
              <input type="checkbox" class="accent-brand-600" :checked="tousCoches" @change="toutCocher" />Tout sélectionner
            </label>
            <button type="button" class="btn-danger btn-sm" :disabled="!selection.size" @click="confirmSuppr = true">
              <Icon name="trash" :size="13" />Supprimer<template v-if="selection.size"> ({{ selection.size }})</template>
            </button>
          </div>
        </div>

        <ul v-if="journal.length" class="divide-y divide-line">
          <li v-for="(j, i) in lignes" :key="j.id" class="flex items-start gap-4 px-6 py-3.5 transition hover:bg-brand-50/50" :title="j.action">
            <input type="checkbox" class="mt-2 accent-brand-600" :checked="selection.has(j.id)" :aria-label="`Sélectionner l'entrée ${i + 1}`" @change="cocher(j.id)" />
            <span class="mt-0.5 grid size-8 shrink-0 place-items-center rounded-full text-xs font-semibold"
              :class="j.erreur ? 'bg-red-100 text-red-700' : 'bg-slate-100 text-slate-600'">
              <Icon v-if="j.erreur" name="alert" :size="14" />
              <template v-else>{{ j.auteur === "système" ? "⚙" : initiales(j.auteur) }}</template>
            </span>
            <div class="min-w-0 flex-1">
              <p class="text-sm leading-relaxed" :class="j.erreur ? 'font-medium text-red-800' : 'text-slate-800'">{{ j.texte }}</p>
              <p v-if="j.detail" class="mt-0.5 text-sm text-slate-500">{{ j.detail }}</p>
              <p class="mt-0.5 text-xs text-slate-400">{{ j.auteur }} · {{ fmtDateTime(j.date) }}</p>
            </div>
            <button type="button" class="btn-ghost btn-sm text-slate-400 hover:text-red-600" aria-label="Supprimer cette entrée" @click="selection = new Set([j.id]); confirmSuppr = true">
              <Icon name="trash" :size="14" />
            </button>
          </li>
        </ul>
        <div v-else class="flex flex-col items-center gap-2 px-6 py-12 text-center">
          <Icon name="list" :size="26" class="text-slate-300" />
          <template v-if="filtreActif">
            <p class="text-sm font-medium text-slate-700">Aucune action sur cette période</p>
            <p class="text-sm text-slate-500">Essayez une autre date.</p>
            <button class="btn-secondary btn-sm mt-2" @click="reinitialiser">Réinitialiser</button>
          </template>
          <template v-else>
            <p class="text-sm font-medium text-slate-700">Choisissez une période</p>
            <p class="text-sm text-slate-500">Sélectionnez une date ou « 7 derniers jours » pour afficher le journal.</p>
          </template>
        </div>
      </section>

      <ConfirmModal :open="confirmSuppr" title="Supprimer du journal ?" confirm-label="Supprimer" :busy="supprBusy" @confirm="supprimerEntrees" @cancel="confirmSuppr = false">
        <p>{{ selection.size }} entrée{{ selection.size > 1 ? 's' : '' }} du journal ser{{ selection.size > 1 ? 'ont' : 'a' }} définitivement supprimée{{ selection.size > 1 ? 's' : '' }}.</p>
      </ConfirmModal>

      <!-- Comptes -->
      <section v-show="tab === 'comptes'" class="space-y-4">
        <!-- Mon profil : photo de profil (ajout et modification) -->
        <div v-if="moi" class="card flex flex-wrap items-center gap-5 p-6">
          <div class="relative">
            <Avatar :nom="moi.email" :src="photoCompte(moi.photo)" :size="84" />
            <button type="button" class="absolute -bottom-1 -right-1 grid size-8 place-items-center rounded-full border-2 border-white bg-brand-600 text-white shadow transition hover:bg-brand-700 disabled:opacity-50"
              :disabled="photoBusy" aria-label="Modifier la photo de profil" @click="fichierPhoto?.click()"><Icon :name="photoBusy ? 'refresh' : 'camera'" :size="15" :class="photoBusy && 'animate-spin'" /></button>
            <input ref="fichierPhoto" type="file" accept="image/png,image/jpeg,image/webp,image/gif" class="sr-only" @change="choisirPhoto" />
          </div>
          <div class="min-w-0 flex-1">
            <h2 class="card-title">Mon profil</h2>
            <p class="mt-0.5 truncate text-sm text-slate-600">{{ moi.email }}</p>
            <p class="mt-1 text-xs text-slate-400">PNG, JPEG, WebP ou GIF · 5 Mo maximum. Le mot de passe se change dans « Paramètres ».</p>
            <div class="mt-3 flex flex-wrap gap-2">
              <button type="button" class="btn-secondary btn-sm" :disabled="photoBusy" @click="fichierPhoto?.click()"><Icon name="camera" :size="14" />{{ moi.photo ? "Modifier la photo" : "Ajouter une photo" }}</button>
              <button v-if="moi.photo" type="button" class="btn-ghost btn-sm" :disabled="photoBusy" @click="retirerPhoto"><Icon name="trash" :size="14" />Retirer</button>
            </div>
          </div>
        </div>

        <!-- Demandes d'inscription : visibles uniquement par le compte principal -->
        <div v-if="moi?.principal && demandes.length" class="card border-amber-200">
          <header class="flex flex-wrap items-center gap-3 border-b border-line px-6 py-4">
            <h2 class="card-title">Demandes d'inscription</h2>
            <span class="badge-blue">{{ demandes.length }}</span>
          </header>
          <ul class="divide-y divide-slate-100">
            <li v-for="d in demandes" :key="d.id" class="flex flex-wrap items-center gap-4 px-6 py-3.5">
              <Avatar :nom="d.email" :size="36" />
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-medium text-slate-900">{{ d.email }}</p>
                <p class="text-xs text-slate-400">Demandé le {{ fmtDateTime(d.date_creation) }}</p>
              </div>
              <button class="btn-ghost btn-sm" :disabled="demandeBusy === d.id" @click="traiterDemande(d, false)"><Icon name="x" :size="14" />Refuser</button>
              <button class="btn-primary btn-sm" :disabled="demandeBusy === d.id" @click="traiterDemande(d, true)"><Icon name="check" :size="14" />Accepter</button>
            </li>
          </ul>
        </div>

        <div class="card">
          <header class="flex flex-wrap items-center gap-3 border-b border-line px-6 py-4">
            <h2 class="card-title">Comptes responsables</h2>
            <span class="badge-slate">{{ comptes.length }}</span>
          </header>
          <p class="border-b border-line bg-slate-50/60 px-6 py-2.5 text-xs text-slate-500">
            Les nouvelles inscriptions apparaissent dans « Demandes d'inscription » et doivent être acceptées par le compte principal. Ici, vous pouvez désactiver ou réactiver un compte déjà accepté.
          </p>
          <ul class="divide-y divide-slate-100">
            <li v-for="c in comptes" :key="c.id" class="flex flex-wrap items-center gap-4 px-6 py-3.5">
              <Avatar :nom="c.email" :src="photoCompte(c.photo)" :size="36" />
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-medium text-slate-900">{{ c.email }}
                  <span v-if="c.moi" class="badge-blue ml-2">Vous</span>
                  <span v-if="c.principal" class="badge-slate ml-2">Principal</span>
                </p>
                <p class="text-xs text-slate-400">Créé le {{ fmtDateTime(c.date_creation) }}</p>
              </div>
              <span :class="c.actif ? 'badge-green' : 'badge-slate'">{{ c.actif ? "Actif" : "Désactivé" }}</span>
              <button v-if="moi?.principal && !c.principal" :class="c.actif ? 'btn-secondary btn-sm' : 'btn-primary btn-sm'" @click="basculerCompte(c)">{{ c.actif ? "Désactiver" : "Réactiver" }}</button>
            </li>
          </ul>
        </div>
      </section>
    </template>
  </div>
</template>