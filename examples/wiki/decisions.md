# decisions

- [2026-01-11][alice] Postgres over MongoDB: we need joins and the ops team already runs Postgres
- [2026-02-14][bob] no ORM on the hot read path — raw SQL in `src/db/queries.ts`, measured 4x faster
- [2026-03-02][alice] background jobs stay in-process (no queue service) until we exceed ~50 jobs/min
