# Versioned encryption and rotation

New ciphertext is `vs1:<key-id>:<Fernet-token>`. The encrypted payload repeats
the exact version/key prefix, so relabeling two IDs that happen to use the same
key cannot bypass authentication. Unknown keys, damaged envelopes and invalid
Fernet authentication fail closed. Existing unprefixed Fernet values remain
readable with the original APP_SECRET derivation. The default `app-v1` ID uses
that same stable material; deploying this format does not silently change keys.
Never change APP_SECRET as an encryption rotation: it also signs sessions and
is still needed to read pre-versioned data.

`KeyProvider` has `active_key_id()` and `key(id)` methods. The default local
provider optionally reads a private `CIPHER_KEYS_JSON` mapping of IDs to URL-safe
base64-encoded32-byte Fernet keys. Set `CIPHER_ACTIVE_KEY_ID` to a NEW ID after
distributing its material to every replica. IDs must never be reused for different
material. Keep all historical keys until migration, validation and backup restore
acceptance are complete. Store actual values securely, never in a command line,
logs, docs, review artifacts or plaintext job payloads. Private configuration was
not changed by this implementation.

The optional `CIPHER_KEY_PROVIDER=azure-key-vault` adapter uses native
DefaultAzureCredential, HTTPS and secrets/get access. Configure CIPHER_VAULT_URL,
CIPHER_VAULT_SECRET_NAME and an active ID equal to the immutable secret version.
The adapter always calls get_secret with that version; it never uses latest.
Fernet material is held in a bounded five-minute cache. New writes fail if the
selected version is unavailable. Original legacy/app-v1 values remain readable.
Other legacy local IDs require retaining their original provider/material during
the migration. A fake SecretClient covers version pinning, caching and failure;
no Azure secret was created, changed, deleted or retrieved in acceptance tests.

Rotation procedure:

1. Provision a new key securely and retain all old keys. Deploy readers that
   support both formats before switching every writer to the new active ID.
2. Review the active ID and job state:
   `uv run python scripts/reencrypt_secrets.py`.
3. Queue a global migration with `--queue --target-key-id <active-id>` or add
   `--workspace-id <uuid>` for tenant-only ciphertext. This queues durable work;
   it does not print material or change provider settings.
4. The dedicated worker executes bounded25-row batches. Alternatively run
   `--run-one-batch` during controlled maintenance. Claims have fenced leases,
   transactional cursor/count checkpoints and append-only audits. Interrupted
   batches roll back and expired claims can recover. Pause/resume/cancel API
   transitions occur between batches.
5. A missing key, damaged ciphertext, schema mismatch or active-ID change blocks
   the job at its checkpoint. Its error has only a category/table/row/column.
   Repair the prerequisite, then use `--resume-job <uuid>` or the operator API.
   Business timestamps and authenticated original Fernet timestamps are preserved.
6. Validate every scoped value and perform a backup restore before retiring any
   key. Key deletion/disable is deliberately never automatic.

The scan includes all `encrypted_*` columns and the existing encrypted webhook
`secret` column. Global jobs include OAuth attempts and mail outbox; tenant jobs
exclude global rows. Published HTTP tool versions permit only ciphertext changes
under a real current running rotation lease. Database triggers still reject
metadata changes, expired/unscoped attempts and deletion. Rotation audit is
append-only. Tests cover both SQLite and restricted-role PostgreSQL.

`/v1/operator/encryption` and `/rotations` require verified browser identity,
CSRF for mutation and the explicit CIPHER_ROTATION_OPERATOR_EMAILS allowlist
(empty by default). Workspace ownership and developer keys do not grant global
encryption privileges. The CLI is for trusted operators with native database
credentials. It never changes .env or asks the API to disclose a key.
