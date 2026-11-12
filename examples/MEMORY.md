# Always-injected. Index only — one line per topic.
# Rule: when you see wiki:<topic>, run `wikimem show <topic>` before answering.

infra: prod 10.0.0.5, staging 10.0.0.6; deploy via ./deploy.sh → wiki:infra
project: Next.js + Postgres; `make dev`, `make test` → wiki:project
decisions: use Postgres not Mongo (ops cost); no ORM for hot paths → wiki:decisions
