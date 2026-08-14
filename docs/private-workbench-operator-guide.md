# Private Workbench v1 operator guide

This workbench is for private development use only. It never writes or promotes a canonical Pack.

## Launch

Open **PrepFlow Workbench** from the Chromebook/Linux Apps menu. It starts or reopens the local Workbench and opens it in the default browser. No terminal is needed.

Use the launcher menu actions to **Stop** a running Workbench or **Restart** it when it is unavailable. To install or update the Apps-menu entry again, run:

```bash
.venv/bin/python tools/install_prepflow_workbench_launcher.py
```

Only if the launcher is unavailable, use this troubleshooting fallback from the private PrepFlow development checkout:

```bash
.venv/bin/python -m ingestion_v2.workbench_server
```

Open http://127.0.0.1:8765/. Ingestion & Clean is always the primary entry page. Use `Repair & Add Questions` in the top navigation to open the integrated question station at `/questions/`; use `Back to Ingestion & Clean` to return. Both stations share the same server, origin, and forwarded port.

## Start an intake

Choose a registered Pack (Fundamentals, Medical-Surgical, or Pharmacy) when the source should be reconciled to that existing Pack. Choose Pediatrics for its registered source-only preset.

Choose **New Source** for a book without a canonical Pack. Provide a display name, Pack slug, and short friendly prefix. The workbench previews both the immutable ID (`PFQ-{slug}-000000001`) and the screenshot reference (`{prefix} 1`) before intake. Slugs and prefixes must be safe and unique; they cannot collide with a registered Pack, alias, or friendly prefix.

PFQ IDs are permanent internal identities used for saves, candidates, reconciliation, and any future Pack work. Friendly references are what students see and report in screenshots. Repair Desk accepts either form, including compact references such as `peds398`, bare numbers, and `?question=` deep links. A bare number may match more than one book.

## Review safely

Complete one Pack or source run at a time. Use the temporary source page to verify content before approving a change. Create field-level proposals only, and explicitly record source verification when the proposal requires it. Use exclusions to quarantine unusable records rather than forcing them into a candidate.

Build only an isolated candidate. A private checkpoint allows a review to reload after a restart; cleanup removes a disposable run when it is no longer needed. Source-only candidates always remain blocked with `source_only_candidate_requires_explicit_pack_creation` and cannot create or promote a canonical Pack.

Ask Rowan is deferred and is not part of Workbench v1.
