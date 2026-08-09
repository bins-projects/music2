"""Validated metadata for isolated source-only intake."""
from __future__ import annotations
import re
from ingestion_v2.domain import DomainError

_SLUG = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9 -]{0,31}$")

def validate_source_metadata(value: dict, *, reserved: set[str]) -> dict:
    name = " ".join(str(value.get("display_name") or "").split())
    slug = str(value.get("slug") or "").strip().casefold()
    prefix = " ".join(str(value.get("prefix") or "").split())
    if not name or not _SLUG.fullmatch(slug) or not _PREFIX.fullmatch(prefix):
        raise DomainError("New Source requires a display name, safe Pack slug, and safe friendly prefix")
    if any(token in name.casefold() + slug + prefix.casefold() for token in ("/", "\\", ".pdf", "private_sources")):
        raise DomainError("New Source identifiers cannot contain paths or source filenames")
    compact = re.sub(r"[^a-z0-9]", "", prefix.casefold())
    reserved_normalized = {item.casefold() for item in reserved}
    if slug in reserved_normalized or compact in reserved_normalized:
        raise DomainError("New Source slug or friendly prefix collides with a registered source")
    return {"display_name": name, "slug": slug, "prefix": prefix}
