# o-browser — Python Browser Automation Client

Async browser automation via Patchright (patched Playwright).

## Install

```bash
pip install o-browser                  # core, from PyPI
pip install o-browser-vivatech         # + un adapter de site (plugin, voir Structure)
pip install -e .                       # editable local (core)
pip install -e adapters/vivatech       # editable local (adapter)
```

Le `.venv` du repo est géré par **uv** (pas de `pip` dedans) — pour builder/installer, utiliser
un python qui a pip. Adapter et core doivent vivre dans le **même environnement** (avec pipx :
`pipx inject oto-cli o-browser-vivatech`), sinon `load_site` ne découvre pas l'entry-point.

## Usage

```python
# Headless
async with BrowserClient() as browser:
    await browser.goto("https://example.com")
    text = await browser.get_text()

# Persistent profile (cookies survive between runs)
async with BrowserClient(profile_path="~/.config/browser/linkedin") as browser:
    await browser.goto("https://linkedin.com")

# Connect to remote Chrome (e.g. o-browser-server)
async with RemoteBrowser("http://host:8080") as browser:
    await browser.goto("https://example.com")
```

## Structure (monorepo)

```
o_browser/                 # core générique — distribution `o-browser`
├── __init__.py    # exports BrowserClient, RemoteBrowser, load_site, available_sites
├── _mixin.py      # PageMixin — shared methods (goto, click, get_text, scroll, screenshot)
├── client.py      # BrowserClient — launches Chrome locally via Patchright
├── har.py         # HARRecorder — capture HAR côté Python (survit à la fermeture user en interactif)
└── remote.py      # RemoteBrowser — connects to remote Chrome via CDP WebSocket

adapters/                  # 1 sous-dossier = 1 distribution séparée (plugin de site)
└── vivatech/              # distribution `o-browser-vivatech`
    ├── pyproject.toml      # entry-point [o_browser.sites] vivatech = o_browser_vivatech:VivaTechClient
    └── o_browser_vivatech/__init__.py  # VivaTechClient (Server Action + objet SSR flight)
```

**Adaptateurs de sites = plugins.** Le core ne contient AUCUN site. Chaque adaptateur est une
distribution à part (dossier sous `adapters/`) qui s'enregistre dans le groupe d'entry-points
`o_browser.sites`. On installe à la carte : `pip install o-browser` (core) + `o-browser-vivatech`.
Découverte à l'exécution :

```python
from o_browser import load_site, available_sites
available_sites()              # -> ['vivatech', ...] (adaptateurs installés)
VivaTechClient = load_site("vivatech")
```

### Ajouter un adaptateur

1. `adapters/<site>/pyproject.toml` — nom `o-browser-<site>`, dep `o-browser>=0.3.0`, entry-point
   `[project.entry-points."o_browser.sites"]` → `<site> = "o_browser_<site>:<Client>"`.
2. `adapters/<site>/o_browser_<site>/__init__.py` — le client, `from o_browser import BrowserClient`.
3. `pip install -e adapters/<site>` (dev) ; publier la distribution séparément.

`record=True` écrit le HAR via `HARRecorder` (buffer Python), pas via le HAR natif Playwright :
ce dernier se perdait quand l'utilisateur fermait la fenêtre en mode interactif (browser mort avant
`context.close()`). La vidéo reste gérée nativement par Playwright.

## Dependencies

- `patchright` (Playwright fork with anti-detection patches)

## Related

- [o-browser-server](https://github.com/AlexisLaporte/o-browser-server) — Docker service (VNC + CDP + recording)
