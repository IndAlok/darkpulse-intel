# Evidence integrity

## Ledger and seal

- Exports are sealed with the SHA-256 of the delivered bytes. The seal is
  returned in the `X-DarkPulse-Evidence-Seal` header.
- Each ledger entry stores the previous entry's hash; `GET /api/v1/evidence/verify`
  walks the chain and reports the first broken link.
- Exports are written by `POST /api/v1/export`. `GET /export` never appends a
  ledger row.

## RFC 3161

RFC 3161 timestamping is not implemented. Setting
`DARKPULSE_RFC3161_ENABLED=true` refuses startup. `tsa_verified` stays false.
A TSA will be wired only with a pinned trust anchor, an HTTPS allowlist, no
redirects, DER storage, and a nonce check, proven by a checked-in fixture.
Until then provenance is hash-only.

## Dedup and content-state TTLs

| Store | Setting | Default | Meaning |
|---|---|---|---|
| Dedup done-key | `DARKPULSE_DEDUP_TTL_SECONDS` | 7776000 (90 days) | How long a published record's `dedup_key` marks it done in Redis. |
| Dedup pending-key | `pending_ttl_seconds` in `RedisDedupStore` | 300 s | Claim hold before publish; short so a crashed publisher's key frees itself. |
| Content state | `ContentStateStore` default | 7776000 (90 days) | How long an artifact's `content_sha256` is remembered, so a re-crawl of unchanged bytes is skipped. |

Renewal: the done-key is written once per successful publish with the full
TTL. The pending-key is written on claim and expires on its own; publish
replaces it with the done-key. A publish that runs longer than 300 s holds
nothing, because the pending-key only guards against a second publisher
starting inside that window; the Mongo unique index on `dedup_key` is the
authority, and the processor forgets the Redis key on `DuplicateKeyError`
(see `processor.process_record`) so a partial write self-heals.