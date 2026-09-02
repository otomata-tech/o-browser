"""
Digitevent — attendee directory export (via authenticated UI, not the private API).

Digitevent (digitevent.com) powers many event-app sites — "Le Grand Bain"
(legrandbain.lafrenchtech-aixmarseille.fr) is one instance, but any event on the
platform shares the same app shell (Vue SPA, /app/attendees/ directory, same
pagination/DOM patterns). This script generalizes to any of them.

Deliberately does NOT touch the private API or lift the session JWT: Digitevent's
own legal notice (digitevent.com/fr/legal/notice-legale, section IV) cites art.
L.341-1 CPI (sui generis database-producer right) against "extraction... totale
ou partielle" — bulk-exporting the guest directory via the reverse-engineered API
crosses that line even for a ticket holder acting in good faith. This script only
drives the browser the way a human attendee would: click through the paginated
UI, read the rendered DOM. Slower, but stays inside normal app usage.

## Setup — one-time, per event, by the human

The event app requires a personal login (email / magic link / 2FA depending on
the event). The agent must never see or handle those credentials — open a
dedicated Chrome profile with CDP enabled and let the human log in themselves:

    google-chrome --remote-debugging-port=9222 \\
      --user-data-dir="$HOME/.config/browser/<event-slug>" \\
      --no-first-run --no-default-browser-check \\
      "https://<event-host>/app/"

Run this via the Bash tool's `run_in_background: true` (a plain `nohup ... &
disown` gets reaped when the sandboxed tool call ends — the process dies a few
seconds after launch, before anyone can log in). Confirm it's alive with
`curl http://localhost:9222/json/version`, tell the human to log in in that
window, and only then run this script.

## Usage

    python digitevent_attendees.py <event-host> [output.csv]

    python digitevent_attendees.py legrandbain.lafrenchtech-aixmarseille.fr attendees.csv
"""

import asyncio
import csv
import re
import sys

from o_browser import RemoteBrowser

CDP_ENDPOINT = "http://localhost:9222"

# Selector notes (Digitevent's app shell, checked 2026-09):
# - Each attendee card is an <a> whose class list includes "group/item" (a
#   Tailwind group-scoping marker, not escapable in a CSS selector — matched
#   via className.includes() in JS instead).
# - Within a card, the three text lines are told apart by class, not position:
#   a card with no job title only renders two lines, which silently mislabels
#   fields if you go by DOM order instead.
EXTRACT_JS = """() => {
    const cards = [...document.querySelectorAll('a')].filter(
        a => (a.className || '').toString().includes('group/item')
    );
    return cards.map(a => {
        const id = (a.getAttribute('href') || '').split('/').filter(Boolean).pop();
        const name = a.querySelector('p.font-medium:not(.text-muted-foreground)')?.textContent.trim() || '';
        const job = a.querySelector('p.text-muted-foreground.font-medium')?.textContent.trim() || '';
        const org = a.querySelector('p.font-semibold')?.textContent.trim() || '';
        return {id, name, job, org};
    });
}"""

MAXPAGE_JS = """() => {
    const nums = [...document.querySelectorAll('nav a[href*="attendees"]')]
        .map(a => { const m = (a.getAttribute('href') || '').match(/page=(\\d+)/); return m ? parseInt(m[1]) : null; })
        .filter(Boolean);
    return nums.length ? Math.max(...nums) : null;
}"""

CUR_PAGE_JS = """() => parseInt(new URL(window.location.href).searchParams.get('page') || '1')"""


def clean(s: str) -> str:
    return re.sub(r"^[+*\s]+|[+*\s]+$", "", s or "").strip()


async def extract_stable(browser, prev_ids, max_wait=8.0, poll=0.4):
    """Poll until the card list is non-empty and differs from the previous page
    (client-side pagination doesn't reload the document, so there's no
    navigation event to await — the SPA just swaps the list contents)."""
    elapsed = 0.0
    last = []
    while elapsed < max_wait:
        batch = await browser.evaluate(EXTRACT_JS)
        ids = {r["id"] for r in batch if r["id"]}
        if ids and (prev_ids is None or ids != prev_ids):
            return batch
        last = batch
        await browser.wait(poll)
        elapsed += poll
    return last


async def scrape_attendees(event_host: str) -> list[dict]:
    seen: dict[str, dict] = {}
    async with RemoteBrowser(CDP_ENDPOINT) as browser:
        await browser.goto(f"https://{event_host}/app/attendees/", wait_until="networkidle")
        batch = await extract_stable(browser, None)
        prev_ids = {r["id"] for r in batch if r["id"]}
        for row in batch:
            if row["id"]:
                seen[row["id"]] = row
        maxpage = await browser.evaluate(MAXPAGE_JS)
        curpage = await browser.evaluate(CUR_PAGE_JS)
        print(f"page {curpage}: +{len(batch)} (total {len(seen)}) maxpage={maxpage}")

        while maxpage and curpage < maxpage:
            clicked = False
            for _ in range(3):
                try:
                    await browser.page.click("a[aria-label='Aller à la page suivante']", timeout=5000)
                    clicked = True
                    break
                except Exception:
                    await browser.wait(0.5)
            if not clicked:
                print("Can't click 'next page', stopping.")
                break

            batch = await extract_stable(browser, prev_ids)
            ids = {r["id"] for r in batch if r["id"]}
            for row in batch:
                if row["id"]:
                    seen[row["id"]] = row
            prev_ids = ids
            newmax = await browser.evaluate(MAXPAGE_JS)
            if newmax:
                maxpage = max(maxpage, newmax)
            curpage = await browser.evaluate(CUR_PAGE_JS)
            print(f"page {curpage}: +{len(batch)} (total {len(seen)}) maxpage={maxpage}")

    return [
        {"name": clean(r["name"]), "job": clean(r["job"]), "org": clean(r["org"]), "id": r["id"]}
        for r in seen.values()
    ]


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    event_host = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else "attendees.csv"

    rows = await scrape_attendees(event_host)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["name", "job", "org", "id"])
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["org"].lower()))
    print(f"TOTAL: {len(rows)} attendees -> {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
