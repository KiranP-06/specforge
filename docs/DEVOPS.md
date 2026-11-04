# How DevOps Is Integrated into SPECForge

Every course practical has a concrete job in the product. This page maps each tool to the file that implements it, what it does for SPECForge, and how to show it working.

## 1. The pipeline at a glance

```
 developer          GitHub Actions (GitHub-hosted)                                         EC2 (self-hosted runner)
 ─────────   ┌──────────────────────────────────────────────────────────────────┐   ┌──────────────────────────────────┐
 feature  ─► │ backend: ruff · pytest (SQLite + Postgres) · alembic check · Bandit│   │ deploy.sh                        │
 branch      │ frontend: eslint · tsc · vitest · vite build                       │   │  kubectl apply -k overlays/aws   │
   │ PR      │ iac: terraform fmt/validate · ansible-lint · kustomize+schema ·    │   │  (image tag = commit SHA)        │
   ▼         │      promtool · compose config                                     │──►│  initContainer: alembic upgrade  │
 review +    │ scan: Trivy deps + secrets (blocking) · Trivy IaC (report)         │   │  rolling update (maxUnavail 0)   │
 merge       │ e2e: build real images → compose up → smoke + blueprint + metrics  │   │  smoke_test.sh                   │
 to main     │ build: docker build → Trivy image scan → push ghcr.io/…:<sha>      │   │  fail ⇒ kubectl rollout undo     │
             └──────────────────────────────────────────────────────────────────┘   └──────────────────────────────────┘
                                                                                                   │
  Terraform (laptop) ─► VPC · SG · EC2 · EIP · S3 · CloudWatch      Ansible ─► harden · Docker · k3s · CW agent · runner · app
                                                                                                   ▼
                                    Prometheus + Grafana (in-cluster)  ·  CloudWatch logs/metrics/alarms  ·  S3 backups
```

## 2. Integration map

| # | Tool | Where | What it does for SPECForge | Show it |
|---|---|---|---|---|
| 01 | **Git / GitHub** | repo, branch rules | Feature branches, PR review, protected `main`, required checks | A PR with green checks and an approval |
| 02 | **GitHub Actions CI** | `.github/workflows/ci-cd.yml` | 6 gating jobs: lint, unit tests on SQLite *and* PostgreSQL+pgvector, migration drift check, SAST, IaC validation, end-to-end test of the real images | *Actions* tab → job graph |
| 02 | **Security gates** | Bandit, Trivy (in CI) | Fails the build on medium+ code issues, fixable HIGH/CRITICAL CVEs, leaked secrets, critical image CVEs | A Trivy step log |
| 03 | **Docker** | `backend/Dockerfile`, `frontend/Dockerfile` | Multi-stage, non-root images with healthchecks; tagged with the commit SHA → GHCR | GHCR package page: one tag per commit |
| 03 | **Docker Compose** | `docker-compose.yml` | Dev stack (Postgres, Redis, migrate, API, worker, Nginx/React) + `monitoring` profile; also the CI end-to-end environment | `docker compose --profile monitoring up` |
| 03 | **Docker Swarm** | `docker-stack.yml` | Interim cluster: replicas, overlay networks, secrets, `start-first` updates with automatic rollback | `docker stack deploy` + `docker service ls` |
| 04 | **Terraform** | `deploy/terraform/` | Whole AWS environment as code: VPC, subnet, IGW, SG (80/443 + SSH from admin IP), EC2 (IMDSv2), Elastic IP, encrypted S3, CloudWatch log groups / metric filter / 4 alarms / dashboard, SNS; remote state in S3 | `terraform plan` → `apply` → outputs |
| 05 | **Ansible** | `deploy/ansible/` (6 roles) | Idempotent host config: OS hardening, Docker, k3s, CloudWatch agent, GitHub runner, app deploy; secrets in Ansible Vault | Run it twice; the second run shows `changed=0` for the setup |
| 06 | **Kubernetes (k3s)** | `deploy/k8s/base`, `overlays/aws`, `overlays/local` | Deployments (api ×2, worker, web ×2), Postgres StatefulSet, Redis, Ingress, ConfigMap/Secrets, probes, resource limits, rolling updates, migration init container, CronJobs | `kubectl get pods -A`, `kubectl rollout history` |
| 06 | **Kustomize overlays** | `deploy/k8s/overlays/*` | One base, two environments: AWS (GHCR, S3, backups) and local k3d (Plan B). Same manifests in both | `kustomize build overlays/aws \| less` |
| 06 | **Database migrations** | `backend/migrations` (Alembic) | Versioned schema; CI checks upgrade/downgrade and drift; pods migrate under a Postgres advisory lock | `alembic history`, the `migrate` init container log |
| 07 | **Smoke tests + rollback** | `scripts/deploy.sh`, `scripts/smoke_test.sh` | Checks web, `/health`, `/ready`, API, OpenAPI, auth, Grafana and the deployed SHA; auto `rollout undo` on failure | Break `/health`, merge, watch the rollback |
| 08 | **Prometheus** | `deploy/k8s/monitoring/` | Scrapes annotated pods + node-exporter; 7 alert rules (API down, 5xx, p95 latency, queue backlog, failing jobs, memory, disk) | `/targets` and `/alerts` pages |
| 08 | **Grafana** | `…/files/specforge-dashboard.json` | Provisioned dashboard: deployed commit, traffic, latency, errors, jobs, queue, quality scores, node health | `http://<ip>/grafana` |
| 08 | **CloudWatch** | Terraform + `roles/cloudwatch` | Container and system logs, memory/disk metrics, alarms → SNS email, AWS-side dashboard | CloudWatch dashboard + a log search |
| — | **S3** | Terraform + `overlays/aws/cronjobs.yaml` | Uploads, exports, nightly `pg_dump` (via instance role, no keys), Terraform state | `kubectl create job --from=cronjob/pg-backup` → object in S3 |

## 3. How one commit reaches production

1. A developer opens a PR. CI runs every quality and security gate. A teammate approves, then merges.
2. On `main`, the **e2e** job builds the actual images and starts the full stack in Docker Compose. It registers a user, generates a blueprint through Redis and Celery, and checks that Prometheus scrapes the API and Grafana has the dashboard. Only then does **build** run.
3. **build** scans each image with Trivy and pushes `ghcr.io/<owner>/specforge-{api,web}:<commit-sha>`.
4. **deploy** runs on the EC2's self-hosted runner. It has no AWS keys; it uses the instance role. It renders `overlays/aws` with the new SHA and applies it.
5. Kubernetes starts new API pods. Their `migrate` init container runs `alembic upgrade head` (one pod at a time, via an advisory lock), then the readiness probe (`/ready`) gates traffic. `maxUnavailable: 0` means zero downtime.
6. `smoke_test.sh` verifies the site, including that `/health` reports the new SHA. Any failure triggers `kubectl rollout undo` on all three deployments.
7. Grafana's *Running build* panel switches to the new SHA. CloudWatch and Prometheus alert if errors or latency rise.

## 4. Same artifacts, three environments

| | Dev | Plan B / staging | Production |
|---|---|---|---|
| Runtime | Docker Compose | k3d (k3s in Docker) | k3s on EC2 |
| Manifests | `docker-compose.yml` | `deploy/k8s/overlays/local` | `deploy/k8s/overlays/aws` |
| Images | built locally | built locally, imported | GHCR, pinned to commit SHA |
| Monitoring | `--profile monitoring` | Prometheus + Grafana | Prometheus + Grafana + CloudWatch |
| Command | `docker compose up` | `scripts/local-k8s.sh up` | merge to `main` |

## 5. Why two monitoring systems

- **Prometheus + Grafana** run inside the cluster and see the *application*: request rate and latency per route, error ratio, jobs, queue depth, blueprint quality, and which build is live.
- **CloudWatch** sits outside the cluster and sees the *infrastructure*. It still works if the cluster is down: EC2 status checks, CPU, logs shipped off the box, and email alarms through SNS.

## 6. Demo script (about 12 minutes)

| Time | Show | Say |
|---|---|---|
| 0:00 | The app at `http://<ip>`: generate a blueprint from the sample brief | "This is the product. Everything you'll see next is how it gets built, shipped and watched." |
| 1:30 | `deploy/terraform` → `terraform plan` (or the outputs) | "The whole AWS environment is code. Security group allows only 80/443, SSH from my IP. IMDSv2. Encrypted S3." |
| 3:00 | `deploy/ansible/site.yml` + a re-run showing `ok`/`changed=0` | "Six idempotent roles take a bare Ubuntu VM to a hardened k3s node with monitoring and a CI runner." |
| 4:30 | Make a small visible change (e.g. a UI label) on a branch → PR | "Every PR runs these gates." Open the Actions job graph. |
| 5:30 | Merge → watch `e2e` → `build` → `deploy` | "Before anything is pushed, CI boots the real images and tests them end to end. Images are tagged with the commit SHA and scanned." |
| 7:30 | `kubectl -n specforge get pods -w` during the rollout; `rollout history` | "Rolling update, zero downtime, migrations run as an init container." |
| 8:30 | Grafana: *Running build* shows the new SHA; latency and traffic panels | "Prometheus scrapes every pod. Seven alert rules." |
| 9:30 | CloudWatch dashboard + alarms; S3 `backups/` | "Logs and infra metrics leave the box. Nightly DB backups go to S3 with no keys stored anywhere." |
| 10:30 | **Rollback demo**: a pre-made branch where `/health` returns 500 → merge → smoke test fails → auto-rollback | "Bad builds never stay live." |
| 11:30 | Wrap-up: the integration map (section 2) | |

**Prepare beforehand:**
- The rollback branch, ready but not yet merged
- A browser tab open on each of: app, Grafana, Actions, CloudWatch
- A terminal SSH'd into the EC2
- Screenshots of a green run and of a rollback, in case Wi-Fi or Learner Lab fails. `scripts/local-k8s.sh up` is the live fallback.

## 7. Questions the panel may ask

- **Why k3s and not EKS?** Learner Lab cannot create IAM roles, and EKS costs about $0.10/h for the control plane alone. k3s is CNCF-certified Kubernetes with the same API and manifests. See `docs/adr/0001`.
- **Where are the secrets?**
  - GitHub holds none for AWS: the deploy uses the instance role.
  - App secrets live in Ansible Vault and become k8s Secrets.
  - Images are pulled with a read-only token.
- **What if a migration breaks?** CI runs upgrade → drift check → downgrade → upgrade on PostgreSQL for every commit. In the cluster, a failing init container blocks the new pods while the old ones keep serving.
- **How do you know what's running?** `/health` returns the git SHA, Grafana shows it, and `kubectl rollout history` records every deploy with its SHA.
- **Can you rebuild from scratch?** Yes: `terraform apply` + `ansible-playbook site.yml`. See Phase 8 of `docs/DEPLOYMENT.md`.
