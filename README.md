# o-browser

Python async browser automation client built on Patchright.

## Install

```bash
pip install o-browser
```

## Usage

```python
from o_browser import BrowserClient, RemoteBrowser

# Local headless browser
async with BrowserClient() as browser:
    await browser.goto("https://example.com")
    text = await browser.get_text()

# Persistent Chrome profile (cookies survive between runs)
async with BrowserClient(profile_path="~/.config/browser/linkedin") as browser:
    await browser.goto("https://linkedin.com")

# With recording (HAR + video)
async with BrowserClient(record=True) as browser:
    await browser.goto("https://example.com")

# Interactive (opens browser window, waits for user to close)
async with BrowserClient(interactive=True) as browser:
    await browser.wait_closed()

# Connect to remote Chrome (e.g. o-browser-full)
# RemoteBrowser auto-creates a session via POST /api/sessions if none active.
async with RemoteBrowser("http://host:8080", workflow="my-app") as browser:
    await browser.goto("https://example.com")

# Disable auto-session if you manage sessions yourself
async with RemoteBrowser("http://host:8080", auto_session=False) as browser:
    ...
```

## Features

- Headless and headful modes
- Persistent Chrome profiles
- HAR + video recording (HAR captured Python-side, survives the user closing the window in interactive mode)
- Proxy support
- Cookie management
- CDP connection to existing Chrome instances
- Anti-detection via Patchright

## Site adapters (plugins)

Site-specific scrapers are **separate distributions**, not bundled in core. Each registers in the
`o_browser.sites` entry-point group and is discovered at runtime:

```python
from o_browser import load_site, available_sites

available_sites()                       # -> ['vivatech', ...] (installed adapters)
VivaTechClient = load_site("vivatech")   # pip install o-browser-vivatech
```

## Scope — kept & consolidated as the local-CLI browser

`o-browser` is the **canonical, kept** browser lib of Otomata, consolidated as the **local-CLI** browser tooling: disco/scraping on your own machine, where a local Chrome (persistent profiles + anti-detection + HAR) is all you need.

**Server-side browser automation in production runs on the hosted [Browserbase](https://www.browserbase.com) substrate** (cf. `oto-backend`) — a real remote Chrome with persistent Contexts and Live View, off-box (anti-OOM). The former self-hosted remote-Chrome service [o-browser-full](https://github.com/otomata-tech/o-browser-full) (VNC + CDP proxy + recording) is **archived/decommissioned**: it overlapped Browserbase entirely and is never needed locally. It stays re-hostable for a sovereign self-hosted setup, which we don't run.
