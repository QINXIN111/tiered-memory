# infra

- [2026-01-12][setup] prod is 10.0.0.5 (2 vCPU / 4 GB), staging is 10.0.0.6
- [2026-01-12][setup] API listens on 8080; nginx terminates TLS on 443
- [2026-02-03][alice] deploy: `./deploy.sh prod` — it runs migrations first, then restarts
- [2026-02-03][alice] rollback script: `./rollback.sh v1.2.0` (never hand-edit the release tag)
- [2026-03-18][bob] backups run 03:10 UTC to object storage; restore tested quarterly
