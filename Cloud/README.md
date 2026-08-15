# Cloud

## Cloud responsibilities

This directory contains infrastructure and operational assets that support the application. It is responsible for repeatable environments, container definitions, deployment automation, configuration management, observability, backups, and recovery procedures. Application business logic belongs outside this directory.

| Path | Purpose |
| --- | --- |
| `docker/` | Container definitions and local container orchestration assets. |
| `deployment/` | Environment-specific deployment manifests and release configuration. |
| `storage/` | Storage provisioning, lifecycle, and access-policy definitions. |
| `scripts/` | Repeatable operational and deployment scripts. |
| `configs/` | Version-controlled, non-secret configuration templates. |
| `monitoring/` | Metrics, logging, alerting, and dashboard configuration. |
| `backup/` | Backup schedules, restore procedures, and recovery verification records. |

## Storage responsibilities

Storage assets define how application data, uploads, logs, and backups are provisioned, secured, retained, and recovered. Apply least-privilege access, encryption in transit and at rest, lifecycle policies, and documented retention periods. Never store production credentials or data exports in this repository.

## Deployment workflow

1. Make infrastructure changes on a focused branch and review the environment impact.
2. Validate configuration and scripts in a non-production environment.
3. Use the approved automated deployment process; do not make undocumented manual production changes.
4. Verify health checks, logs, metrics, and rollback readiness after deployment.
5. Record the released version and any operational follow-up needed.

## Environment variable rules

- Keep only non-secret templates, defaults, and variable names in `configs/`.
- Store actual secrets in the approved secret manager or CI/CD secret store.
- Use separate values for local, test, staging, and production environments.
- Do not commit `.env` files containing credentials, tokens, connection strings, or private keys.
- Document required variables, allowed formats, and safe defaults without exposing values.

## Backup strategy

Back up stateful production data on a defined schedule, retain copies according to the agreed recovery policy, and encrypt backup data. Keep backups separate from the primary environment, monitor each job, and test restores regularly. Store runbooks and restore-verification evidence in `backup/`; never commit backup contents to Git.
