"""
VivaTechClient — scraper de l'annuaire exposants VivaTech (vivatech.com).

Le site est un Next.js App Router (données inwink). Il n'expose pas d'API REST :
- la **liste** (scroll infini) passe par une Server Action `POST /exhibitors?page=N`
  (header `next-action`), réponse RSC dont la ligne `1:{"data":[...]}` porte 20 exposants ;
- la **fiche** n'a pas d'endpoint JSON : l'objet complet (49 champs) est SSR dans le HTML
  du document `/exhibitors/<slug>`, dans le payload flight Next.

Deux contraintes dictent la méthode :
1. Anti-bot **GTAB** : un Chrome headless reçoit 403. Il faut `headless=False` (défaut ici)
   + idéalement un profil persistant. Une 403 lève une erreur explicite.
2. Le `next-action` est **lié au build** (change à chaque redeploy). On le **capture
   dynamiquement** (un scroll déclenche un POST qu'on intercepte) plutôt que de le coder en dur.

Les requêtes sont rejouées **depuis l'intérieur de la page** (`page.evaluate(fetch(...))`)
pour hériter des cookies + fingerprint et passer GTAB.

Adapter o-browser (distribution `o-browser-vivatech`, entry-point `o_browser.sites:vivatech`).

Exemple :

    from o_browser import load_site
    VivaTechClient = load_site("vivatech")
    async with VivaTechClient(profile_path="~/.config/browser/vivatech") as vt:
        exhibitors = await vt.scrape(enrich=True, progress=print)
"""

import json
from typing import Callable, Dict, List, Optional

from o_browser import BrowserClient

BASE = "https://vivatech.com"

# Boucle la Server Action page par page jusqu'à épuisement ; renvoie toutes les lignes.
_LIST_JS = r"""
async (cfg) => {
  const {action, tree, filters, maxPages} = cfg;
  const all = [];
  let page = 1;
  for (; page <= maxPages; page++) {
    const res = await fetch('/exhibitors?page=' + page, {
      method: 'POST',
      headers: {
        'accept': 'text/x-component',
        'content-type': 'text/plain;charset=UTF-8',
        'next-action': action,
        'next-router-state-tree': tree,
      },
      body: JSON.stringify([Object.assign(
        {page: page, search: '$undefined', sectors: '$undefined', company_type: '$undefined',
         fundraising: '$undefined', tags: '$undefined', label: '$undefined'}, filters || {}, {page: page})]),
    });
    if (res.status !== 200) return {error: 'status ' + res.status + ' @ page ' + page, all};
    const text = await res.text();
    let rows = null;
    for (const line of text.split('\n')) {
      const m = line.match(/^[0-9a-f]+:(.*)$/);
      if (!m) continue;
      try { const o = JSON.parse(m[1]); if (o && Array.isArray(o.data)) { rows = o.data; break; } } catch (e) {}
    }
    if (!rows || rows.length === 0) break;
    all.push(...rows);
    await new Promise(r => setTimeout(r, 120));
  }
  return {all, lastPage: page};
}
"""

# Fetch in-page d'un lot de fiches ; renvoie l'objet exposant échappé (slice du flight HTML).
_DETAIL_JS = r"""
async (cfg) => {
  const {slugs, delay} = cfg;
  const out = [];
  for (const slug of slugs) {
    let rec = null, status = 0, err = null;
    try {
      const res = await fetch('/exhibitors/' + slug, {headers: {'accept': 'text/html'}});
      status = res.status;
      if (status === 200) {
        const html = await res.text();
        const marker = html.indexOf(',\\"isPreview\\"');
        if (marker > 0) {
          let i = marker - 1;
          while (i > 0 && html[i] !== '}') i--;
          let depth = 0, start = -1;
          for (let j = i; j >= 0; j--) {
            const c = html[j];
            if (c === '}') depth++;
            else if (c === '{') { depth--; if (depth === 0) { start = j; break; } }
          }
          if (start >= 0) rec = html.slice(start, i + 1);
        }
      }
    } catch (e) { err = e.message; }
    out.push({slug, status, rec, err});
    if (delay) await new Promise(r => setTimeout(r, delay));
  }
  return out;
}
"""


def _unescape_object(escaped: str) -> dict:
    """Le flight encode l'objet en chaîne JS (quotes en \\"). Double json.loads → dict (UTF-8 sûr)."""
    return json.loads(json.loads('"' + escaped + '"'))


class VivaTechClient(BrowserClient):
    """Client de scraping de l'annuaire exposants VivaTech, par-dessus BrowserClient."""

    def __init__(self, *args, **kwargs):
        # L'anti-bot GTAB bloque le headless : on impose le mode visible par défaut.
        kwargs.setdefault("headless", False)
        super().__init__(*args, **kwargs)

    async def open_directory(self) -> None:
        """Charge l'annuaire et lève si l'anti-bot répond 403."""
        await self.goto(f"{BASE}/exhibitors", timeout=45000)
        await self.wait(3)
        text = await self.get_text()
        if "FORBIDDEN" in text.upper() and "403" in text:
            raise RuntimeError(
                "VivaTech anti-bot (GTAB) a renvoyé 403. Utiliser headless=False "
                "avec un profil persistant (idéalement authentifié)."
            )

    async def _capture_action(self) -> tuple[str, str]:
        """Capture le `next-action` + state-tree en déclenchant un POST de pagination via scroll."""
        box: Dict[str, str] = {}

        async def grab(request):
            if box:
                return
            try:
                if request.method != "POST" or "/exhibitors" not in request.url:
                    return
                headers = await request.all_headers()
                if "next-action" in headers:
                    box["action"] = headers["next-action"]
                    box["tree"] = headers.get("next-router-state-tree", "")
            except Exception:
                pass

        self.page.on("request", grab)
        try:
            for _ in range(8):
                await self.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await self.wait(1.5)
                if box:
                    break
        finally:
            self.page.remove_listener("request", grab)

        if "action" not in box:
            raise RuntimeError(
                "Impossible de capturer la Server Action VivaTech (structure de page changée ?)."
            )
        return box["action"], box["tree"]

    async def list_exhibitors(
        self, filters: Optional[Dict[str, str]] = None, max_pages: int = 500
    ) -> List[dict]:
        """Liste complète des exposants (dédupliquée par id) via la Server Action paginée.

        `filters` : surcharge les filtres de l'action (`search`, `sectors`, `company_type`,
        `fundraising`, `tags`, `label`). Par défaut tous à `$undefined` = annuaire complet.
        """
        await self.open_directory()
        action, tree = await self._capture_action()
        result = await self.page.evaluate(
            _LIST_JS, {"action": action, "tree": tree, "filters": filters or {}, "maxPages": max_pages}
        )
        if result.get("error"):
            raise RuntimeError(f"Pagination VivaTech échouée : {result['error']}")
        seen: Dict[str, dict] = {}
        for row in result.get("all", []):
            seen[row.get("id")] = row
        return list(seen.values())

    async def get_exhibitor(self, slug: str) -> Optional[dict]:
        """Objet complet (49 champs) d'un exposant, ou None si la fiche n'a pas l'objet standard.

        Le fetch in-page utilise une URL relative : on s'assure d'être sur le domaine VivaTech.
        """
        if not (self.page.url or "").startswith(BASE):
            await self.open_directory()
        recs = await self.enrich([slug])
        return recs.get(slug)

    async def enrich(
        self,
        slugs: List[str],
        batch: int = 25,
        delay_ms: int = 80,
        progress: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, dict]:
        """Récupère l'objet complet de chaque slug (fetch in-page batché). Renvoie slug -> record.

        Les slugs dont la fiche n'expose pas l'objet standard (ex. placeholders) sont omis.
        """
        out: Dict[str, dict] = {}
        total = len(slugs)
        for bi in range(0, total, batch):
            chunk = slugs[bi:bi + batch]
            rows = await self.page.evaluate(_DETAIL_JS, {"slugs": chunk, "delay": delay_ms})
            for r in rows:
                if r.get("status") == 200 and r.get("rec"):
                    try:
                        out[r["slug"]] = _unescape_object(r["rec"])
                    except Exception:
                        pass
            if progress:
                progress(min(bi + batch, total), total)
        return out

    async def scrape(
        self, enrich: bool = False, progress: Optional[Callable] = None
    ) -> List[dict]:
        """Annuaire complet. Si `enrich=True`, chaque exposant est remplacé par sa fiche complète
        (49 champs) ; les exposants sans fiche standard gardent leur enregistrement de liste."""
        listing = await self.list_exhibitors()
        if not enrich:
            return listing
        slugs = [e["slug"] for e in listing]
        details = await self.enrich(slugs, progress=progress)
        return [details.get(e["slug"], e) for e in listing]
