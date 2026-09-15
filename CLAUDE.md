# o-browser — Python Browser Automation Client

Async browser automation via Patchright (patched Playwright). Monorepo : `o_browser/`
(core générique, distribution PyPI `o-browser`) + `adapters/<site>/` — un sous-dossier =
une distribution séparée = un plugin de site, enregistré via l'entry-point
`o_browser.sites`. Le core ne contient AUCUN site.

## Install

```bash
pip install o-browser                  # core, depuis PyPI
pip install o-browser-vivatech         # + un adapter de site (plugin)
pip install -e .                       # editable local (core)
pip install -e adapters/vivatech        # editable local (adapter)
```

Le `.venv` du repo est géré par **uv** (pas de `pip` dedans) : pour builder/installer,
utiliser un python qui a pip. Adapter et core doivent vivre dans le **même
environnement** (avec pipx : `pipx inject oto-cli o-browser-vivatech`), sinon
`load_site` ne découvre pas l'entry-point.

## Usage

```python
async with BrowserClient(profile_path="~/.config/browser/linkedin") as browser:
    await browser.goto("https://example.com")

from o_browser import load_site, available_sites
VivaTechClient = load_site("vivatech")
```

**Profil persistant ≠ session.** Un `profile_path` conserve les cookies *persistants*
(à date d'expiration), PAS les **session cookies** — Chrome les purge à la fermeture du
contexte. Un login dont la session repose sur des session cookies (cas CAS type
elnet/lemediasocial) ne survit donc pas d'une instance à l'autre : faire le login ET les
actions authentifiées **dans la même instance** `BrowserClient`.

## Ajouter un adaptateur de site

1. `adapters/<site>/pyproject.toml` — nom `o-browser-<site>`, dep `o-browser>=0.3.0`,
   entry-point `[project.entry-points."o_browser.sites"]` → `<site> = "o_browser_<site>:<Client>"`.
2. `adapters/<site>/o_browser_<site>/__init__.py` — le client, `from o_browser import BrowserClient`.
3. `pip install -e adapters/<site>` (dev) ; publier la distribution séparément.

## Publier (PyPI)

Chaque distribution se publie **séparément** (core à la racine, chaque
`adapters/<site>/`). `hatch` ne marche pas ici (pas de `python`) → `build` + `twine`
dans un venv :

```bash
python3 -m venv /tmp/buildenv && /tmp/buildenv/bin/pip install build twine
cd <dir>  # racine pour o-browser, adapters/<site> pour un adapter ; bump version d'abord
rm -rf dist && /tmp/buildenv/bin/python -m build
TWINE_USERNAME=__token__ TWINE_PASSWORD="$(sops -d --extract '["PYPI_TOKEN"]' ~/.otomata/secrets/secrets.yaml)" \
  /tmp/buildenv/bin/twine upload dist/*
```

## Pièges

- `record=True` écrit le HAR via `HARRecorder` (buffer Python), pas via le HAR natif
  Playwright : ce dernier se perd si l'utilisateur ferme la fenêtre en mode interactif
  (browser mort avant `context.close()`). La vidéo reste gérée nativement par Playwright.

## Related

- Service Docker distant (VNC + proxy CDP + enregistrement) : `otomata-tech/o-browser-full`, voir son CLAUDE.md.
