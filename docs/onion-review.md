# Onion seed review

Onion collection ships disabled. `config/onion-review.json` ships with an
empty `approved` list, and no seed enters the corpus until an operator adds
it here after review.

## Review checklist

Before adding a seed to `approved`, record:

1. **Authority** — the legal or organizational authority that permits
   collection, with a date and reference.
2. **Purpose** — the investigation the seed serves.
3. **Scope** — the single onion address and the page/depth limits that keep
   the crawl bounded.
4. **Reviewer** — the named person who approved it.

## File format

```json
{
  "policy_version": "local-review-v1",
  "approved": [
    {
      "source_id": "example-market",
      "onion_address": "…onion",
      "authority": "…",
      "reviewed_by": "…",
      "reviewed_at": "2026-10-08",
      "notes": "…"
    }
  ]
}
```

A source in `config/sources.json` whose `locator` is an onion address is
refused unless its `source_id` appears in this file. Adding a row here is the
only way an onion source runs. Removing the row stops future collection
without deleting historical records.
