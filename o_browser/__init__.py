from importlib.metadata import entry_points

from .client import BrowserClient
from .remote import RemoteBrowser

# Site adapters (LinkedIn, VivaTech, ...) are NOT bundled in core. Each ships as its own
# distribution and registers in the "o_browser.sites" entry-point group. The core only
# discovers them at runtime — install the ones you need (e.g. `pip install o-browser-vivatech`).
_SITES_GROUP = "o_browser.sites"


def available_sites() -> list:
    """Names of the installed site adapters (entry-point group 'o_browser.sites')."""
    return sorted(ep.name for ep in entry_points(group=_SITES_GROUP))


def load_site(name: str):
    """Return the client class for an installed site adapter, by name.

    Raises KeyError (listing what's installed) if the adapter isn't installed.
    """
    for ep in entry_points(group=_SITES_GROUP):
        if ep.name == name:
            return ep.load()
    raise KeyError(
        f"o-browser site adapter '{name}' introuvable. Installés : {available_sites()}. "
        f"Installer l'adapter, ex. `pip install o-browser-{name}`."
    )


__all__ = ["BrowserClient", "RemoteBrowser", "load_site", "available_sites"]
