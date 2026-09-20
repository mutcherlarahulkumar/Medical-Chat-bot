# Skin Tracker API

`openapi.yaml` is the contract — OpenAPI 3.1, 10 paths, 16 schemas. It validates,
and it generates Go that compiles (verified with `oapi-codegen` + `go vet`).

## Generate the Go server

```bash
go install github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen@latest

cat > cfg.yaml <<'YAML'
package: api
output: internal/api/gen.go
generate:
  std-http-server: true    # or chi-server / echo-server / gin-server
  models: true
  strict-server: true      # typed request/response objects, no manual binding
  embedded-spec: true      # lets you serve the spec and validate requests
YAML

oapi-codegen -config cfg.yaml api/openapi.yaml
```

You then implement one interface — `StrictServerInterface`, 16 methods. The
strict server handles decoding, status codes and content types, so your handlers
are `func(ctx, TypedRequest) (TypedResponse, error)` and never touch
`http.ResponseWriter`.

Generated types are idiomatic: `time.Time`, `openapi_types.UUID`,
`openapi_types.Date`, pointers for nullables, and `As…`/`From…` helpers for the
one union (`SyncConflict.ServerValue`).

## Three decisions that drive the whole shape

**The client mints ids.** UUIDs (v7 — time-sortable, index-friendly) are
generated on the phone. That's why creates are `PUT /products/{id}`, not `POST`:
a create can be queued offline, retried on a flaky connection, and land twice
without producing duplicates. Never auto-increment; the phone can't invent a
server sequence while offline.

> ⚠️ **The Android app needs a change for this.** It currently uses Room
> `autoGenerate = true` `Long` ids. Those can't sync — two devices both create
> id 4 and collide. Switch `Routine.id` / `Step.id` to `String` UUIDs before
> wiring this up. Cheap now, painful after real data exists.

**Reminder times are wall-clock, never instants.** A routine stores `hour`,
`minute`, `repeat_mask` and an IANA `timezone`. Store a UTC instant instead and
07:00 becomes 02:30 when the user lands in another country, and shifts twice a
year at daylight saving. Only `done_at` — a thing that actually happened — is
UTC.

`repeat_mask` is 7 bits, **bit 0 = Monday** (matching `java.time.DayOfWeek`,
where Monday is 1). `127` every day, `31` weekdays, `96` weekends, `0` fire once.
In Go: `mask & (1 << (int(t.Weekday()+6) % 7))` — note `time.Weekday` starts at
Sunday, so it needs that shift. This is exactly the off-by-one that will bite
you; the Android side has 18 unit tests pinning the same semantics, worth
porting.

**Everything soft-deletes.** A row deleted on one device must be
distinguishable from one the other device hasn't seen yet, so `DELETE` sets
`deleted_at` and sync returns tombstones. Purge only once every device's cursor
has moved past them.

## The sync loop

```
  pull:  GET /sync?cursor=<last>     → changes + tombstones + new cursor
  push:  POST /sync                  → LWW on updated_at, conflicts returned
```

Pull first, then push — a client that pushes blind overwrites changes it hasn't
seen. Persist the new cursor **only after the page is committed locally**, so a
crash mid-page re-fetches rather than skipping.

Conflicts resolve last-write-wins on `updated_at`, ties to the server. Rows the
server rejected come back in `conflicts` with the authoritative value; the client
overwrites locally. Retrying a rejected push is always wrong.

LWW is the right call for this app — one user, a couple of devices, and the
"conflict" is nearly always the same person editing the same routine twice. It
does mean a simultaneous edit on two phones loses one side silently. If that ever
matters, the upgrade is per-field timestamps, not a rewrite.

### A cursor that doesn't lose writes

The obvious cursor — an `updated_at` timestamp — drops rows when two writes share
a millisecond or a transaction commits out of order. Use a monotonic sequence
instead:

```sql
CREATE SEQUENCE change_seq;
ALTER TABLE products ADD COLUMN seq BIGINT NOT NULL DEFAULT nextval('change_seq');
CREATE INDEX ON products (user_id, seq);
-- bump seq on every UPDATE via trigger
```

Then the cursor is `base64(seq)`, `WHERE seq > $cursor ORDER BY seq LIMIT $n`, and
nothing can slip between pages. Keep `updated_at` for conflict resolution — the
two jobs are different.

## Suggested tables

```sql
users      (id uuid pk, email citext unique, password_hash text, created_at)
products   (id uuid, user_id uuid, name, brand, notes,
            created_at, updated_at, deleted_at, seq bigint,
            primary key (user_id, id))
routines   (id uuid, user_id uuid, name, hour smallint, minute smallint,
            repeat_mask smallint, timezone text, enabled bool,
            created_at, updated_at, deleted_at, seq bigint,
            primary key (user_id, id))
routine_items (routine_id uuid, position int, product_id uuid, note text,
            primary key (routine_id, position))
checkoffs  (user_id uuid, routine_id uuid, product_id uuid, local_date date,
            done bool, done_at timestamptz,
            created_at, updated_at, deleted_at, seq bigint,
            primary key (user_id, routine_id, product_id, local_date))
```

Scope every query by `user_id` — the natural keys are only unique per user, and
a missing `user_id` predicate is a cross-tenant data leak, not just a bug.
`routine_items` is rewritten wholesale on each `PUT /routines/{id}`, which is why
there's no separate items endpoint: reordering stays atomic and bumps one
`updated_at`.

## Things worth getting right

- **`If-Unmodified-Since`** on both `PUT`s gives you optimistic concurrency for
  interactive edits. Honour it — return `412` rather than clobbering.
- **Validate `timezone`** against the IANA database (`time.LoadLocation`), not a
  regex. A bad zone means alarms silently never fire.
- **Reject `local_date` far from the server's date** — more than a day or two out
  usually means a device with a broken clock, and those rows poison the history.
- **Rate-limit `/auth/token`** and hash with argon2id or bcrypt.
- `next_occurrence_at` is advisory. The phone schedules its own alarms offline
  and is authoritative; don't let the server's view drive notifications.

## What isn't in here

No push notifications (the phone's own `AlarmManager` handles reminders — the
server doesn't need to wake anything), no photo storage, no sharing between
users. Say the word if any of those should be added.
