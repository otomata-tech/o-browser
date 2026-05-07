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
- HAR + video recording
- Proxy support
- Cookie management
- CDP connection to existing Chrome instances
- Anti-detection via Patchright

## Related

For a full remote browser service with VNC, session management, and recording, see [o-browser-full](https://github.com/otomata-tech/o-browser-full).
