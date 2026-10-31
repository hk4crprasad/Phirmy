# Delete an agent and its data

Workspace owners and admins can select **Delete agent** on an agent card or in its editor. The dialog loads an impact preview, shows affected categories/counts and retained resources, and requires the exact saved agent name before **Delete permanently** becomes available. **Cancel** makes no change. **Archive instead** hides/disables the agent while preserving history.

Permanent deletion affects one agent, not the whole workspace. It immediately archives the agent, disables its widgets, closes its chats, stops scheduled recrawls, cancels queued related tasks/campaigns and unassigns its phone numbers. Existing widget sessions can no longer use it. Active calls, running related jobs or tool actions must finish or be stopped before deletion can be accepted.

Cleanup runs independently of the browser. **Operations → Agent data deletion** displays progress, completion/errors and **Retry deletion** for owners/admins. An interrupted/provider-failed cleanup retains a manifest and is idempotent on retry. Confirmed deletion cannot be canceled; storage deletions already performed cannot be undone. A failure leaves the agent disabled until cleanup is completed.

## Removed and preserved

The cleanup removes the agent/draft/published versions, installations/logos, website assistant records, chats/messages/context/tickets, attributable captured leads, local booking/availability/appointment records, campaigns/attempts, recordings/transcripts, associated tasks/tool executions and exclusively owned knowledge/products. Knowledge cleanup removes source/chunk/snapshot records, unshared stored source files, Qdrant points filtered by workspace **and** snapshot IDs, and derived Redis embedding-cache keys for those chunks.

Existing references in other agents' drafts or published versions protect shared knowledge. Content-addressed blobs referenced by retained sources, widgets, recordings, products or jobs are preserved. Deleting knowledge is marked unavailable for new agent attachment/publishing or recrawling while cleanup is pending. Snapshot row locks serialize configuration changes with deletion acceptance.

Workspace contacts, integration credentials, shared tools/models/knowledge and unrelated agents/data remain. Phone numbers remain purchased/provisioned and are unassigned. Billing ledger and audit records remain immutable. Calls required by billing/reservations retain minimal records with agent reference, destination, analysis and conversation metadata cleared; their transcript/audio is removed. External calendar meetings are not canceled, and previously exported files/webhook deliveries or provider-side histories are not retracted. These retained boundaries are explained in the confirmation dialog.

## API and migration

- `GET /v1/workspaces/{workspace_id}/agents/{agent_id}/deletion-preview` returns counts, shared-knowledge count and blockers; no raw storage keys are exposed.
- `POST /v1/workspaces/{workspace_id}/agents/{agent_id}/delete` with `{"confirmation":"Exact agent name"}` returns202 and the cleanup job. Repeated acceptance returns the same job. A different/missing name is rejected. This requires an authenticated owner/admin, workspace membership and CSRF; scoped API keys cannot approve deletion.
- Existing owner/admin job retry and status routes handle failures. Permanent deletion jobs cannot be canceled or retried by ordinary builders.

Schema revision is now **2026-10-24-agent-deletion**, still64tables. A migration is necessary for production: PostgreSQL's published-version trigger still blocks updates and ordinary deletes, with a narrow delete exception only for the matching workspace/agent's running deletion job while the agent is archived. Ledger/audit/HTTP-tool-version protection is unchanged. SQLite has the corresponding conditional delete guard. Production runtime does no schema DDL and rejects an outdated revision.

For a local Compose installation, back up the database, then run the migration with the configured migration-capable connection before starting the new API:

```sh
git pull
docker compose build api web
docker compose run --rm api python scripts/migrate_database.py
docker compose up -d api web
```

If production uses a restricted runtime database role, the migration must use the separate migration-role connection. The migration command is present in the API image. Development startup applies the additive trigger/revision change automatically. No private `.env` or remote Supabase migration was changed/performed as part of implementation.

## Verification — 24 October 2026

The full isolated backend suite passes **378 tests with2intentional skips**. The final eight focused deletion cases cover full graph deletion, key invalidation, typed confirmation/cancel, retry after storage failure, immutable billing/minimal call records, preserved shared knowledge/content-addressed blobs, vector filter scope, Redis keys, workspace/role guards, active work blockers and prevention of new attachment/recrawl during deletion. Disposable PostgreSQL17 passes migration/reinitialization, restricted runtime without schema CREATE, ordinary-version-delete denial and confirmed deletion. The container and only its temporary data are removed afterward; no supplied Supabase or real workspace is used.

Production browser acceptance uses an isolated local API/objects and synthetic agents. It passes agent-list/editor controls, wrong-name disabling, Cancel, mobile dialog bounds, shared-knowledge preservation, worker completion and Operations status, archive alternative and zero page errors. Actual screenshots/results are ignored artifacts in `artifacts/agent-deletion/`. No real customer agent or cloud object was deleted in these tests. Qdrant/Redis cleanup requests are tested at the provider boundary with synthetic services; the local object store is exercised directly.

Reproduction:

```sh
UV_CACHE_DIR=/workspace/.cache/uv uv run pytest -q tests/test_agent_deletion.py
.venv/bin/python scripts/verify_agent_deletion_postgres.py
UV_CACHE_DIR=/workspace/.cache/uv uv run python scripts/verify_agent_deletion_browser.py
```
