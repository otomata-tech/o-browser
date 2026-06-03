# o-browser-vivatech

VivaTech exhibitors directory adapter for [o-browser](https://pypi.org/project/o-browser/).

Scrapes the [vivatech.com](https://vivatech.com) exhibitors directory (a Next.js App Router site —
no public REST API): the listing via its paginated Server Action, each exhibitor's full record
(49 fields: website, LinkedIn, city, headcount, funding, "looking for", full description…) from the
SSR flight payload. Requests are replayed from inside the page to pass the anti-bot, so a **headful**
Chrome with a persistent profile is required (headless gets a 403).

## Install

```bash
pip install o-browser-vivatech
```

## Usage

```python
from o_browser import load_site

VivaTechClient = load_site("vivatech")   # registered via the o_browser.sites entry-point
async with VivaTechClient(profile_path="~/.config/browser/vivatech") as vt:
    exhibitors = await vt.scrape(enrich=True)   # ~2100 exhibitors, full records
```

Also available as `oto browser vivatech` via [`oto-cli[vivatech]`](https://pypi.org/project/oto-cli/).
