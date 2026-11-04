# SPECForge Deployment Runbook

This runbook takes SPECForge from your laptop to a monitored production deployment on **AWS Academy Learner Lab**. Do the phases in order. Each phase lists what to run and how to check it worked.

```
01 Code ─► 02 CI ─► 03 Build & Push ─► 04 Provision ─► 05 Configure ─► 06 Deploy ─► 07 Verify ─► 08 Monitor
 GitHub    Actions    Docker → GHCR      Terraform       Ansible          k3s          smoke tests   CloudWatch
```

**Who does what**

| Runs on | Does |
|---|---|
| **Your laptop** | Terraform (provision) and Ansible (configure). Both use your Learner Lab session credentials. |
| **GitHub-hosted runners** | Lint, tests, SAST, Trivy scans, Docker build, push to GHCR. No AWS access needed. |
| **Self-hosted runner on the EC2** | Deploy: `kubectl set image` → rollout → smoke test → auto-rollback. It uses `LabInstanceProfile`, so **no AWS keys are ever stored in GitHub**. |

---

## Phase 0 · Install tools (once)

| Tool | Version | Check |
|---|---|---|
| Git | any | `git --version` |
| Docker Desktop | 24+ | `docker compose version` |
| Python | 3.12 | `python --version` |
| Node.js | 22 | `node --version` |
| Terraform | **≥ 1.10** (needed for S3 native state locking) | `terraform version` |
| Ansible | ansible-core 2.16+ | `ansible --version` |
| AWS CLI | v2 | `aws --version` |

> **Windows:** run Terraform and Ansible inside **WSL2 (Ubuntu)**, because Ansible does not run natively on Windows. Keep the repo inside the WSL filesystem (`~/specforge`), not `/mnt/c/...`, or SSH key permissions break.

## Phase 1 · Run it locally first

```bash
cp .env.example .env
docker compose up --build
```

Open http://localhost:8080, register (the first user becomes admin), and generate a blueprint from the sample brief.
✅ Check: the Dashboard shows a quality score around 94 and the Quality tab lists one contradiction and one duplicate.

## Phase 2 · GitHub repository and CI (01 → 03)

1. **Create the repo** (private is fine) and push:
   ```bash
   git init -b main && git add . && git commit -m "SPECForge initial import"
   git remote add origin https://github.com/<you>/specforge.git && git push -u origin main
   ```
2. **Protect `main`**: *Settings → Branches → Add rule* (or *Rulesets*):
   - Require a pull request before merging, with **1 approval** (your teammates review)
   - Require status checks: `Backend · lint, test, SAST`, `Frontend · lint, typecheck, test, build`, `IaC · terraform, ansible, k8s`, `Trivy · dependencies & IaC`
   - Block force pushes
3. **Create the `production` environment**: *Settings → Environments → New → `production`*
   - Optional: add yourself as a required reviewer to get a manual approval gate before each deploy
   - Add the environment **variable** `APP_URL` = `http://<elastic-ip>` (fill it in after Phase 4)
4. **Watch the first run**: *Actions* tab. `backend`, `frontend`, `iac` and `scan` run on every PR and push. On `main`, `build` pushes two images:
   - `ghcr.io/<you>/specforge-api:<commit-sha>` and `:latest`
   - `ghcr.io/<you>/specforge-web:<commit-sha>` and `:latest`

   The **deploy** job will sit *queued* (“Waiting for a runner”). That is expected: the runner gets installed on the EC2 in Phase 5, and the queued job then runs automatically.
5. **Image pull access.** Choose one:
   - **Easiest:** make both packages public (*your profile → Packages → specforge-api → Package settings → Change visibility → Public*; repeat for `specforge-web`).
   - **Private:** create a classic PAT with only `read:packages` and put it in `vault_ghcr_pull_token` (Phase 5).

✅ Check: the Actions run is green up to `build`, and both packages appear under your GitHub profile.

## Phase 3 · AWS Academy Learner Lab credentials

Learner Lab gives temporary credentials that **expire when the session ends (about 4 h)**. Repeat steps 2–3 every session in which you run Terraform.

1. Open the course → **Modules → Launch AWS Academy Learner Lab → Start Lab**, then wait for the green dot.
2. **AWS Details → AWS CLI: Show** → copy the block into `~/.aws/credentials` (replacing the `[default]` section).
3. **AWS Details → Download PEM** → `labsuser.pem`:
   ```bash
   mv ~/Downloads/labsuser.pem ~/.ssh/ && chmod 400 ~/.ssh/labsuser.pem
   aws sts get-caller-identity          # should print an assumed-role/voclabs ARN
   ```

## Phase 4 · Provision with Terraform (04)

```bash
cd deploy/terraform

# 4a. One-time: bucket for remote state
terraform -chdir=bootstrap init
terraform -chdir=bootstrap apply                       # type "yes"
cp backend.hcl.example backend.hcl
#   → put the bucket name from: terraform -chdir=bootstrap output -raw state_bucket

# 4b. Variables
cp terraform.tfvars.example terraform.tfvars
#   → admin_cidr = "<your public IP>/32"   (curl -s ifconfig.me)
#   → alarm_email = "you@example.com"      (optional)

# 4c. The course practical sequence
terraform init -backend-config=backend.hcl
terraform fmt -check
terraform validate
terraform plan -out tfplan
terraform apply tfplan

# 4d. Hand-off to Ansible
terraform output -raw ansible_inventory > ../ansible/inventory.ini
terraform output public_ip
```

This creates a VPC, public subnet, IGW and route table, a security group (80/443 open, SSH only from your IP), a `t3.large` Ubuntu 24.04 EC2 instance with `LabInstanceProfile` and IMDSv2 (hop limit 2, so pods can use the instance role), an Elastic IP, an encrypted and versioned S3 bucket with lifecycle rules, CloudWatch log groups, a 5xx metric filter, four alarms (CPU, status check, 5xx, queue backlog), an SNS topic and a dashboard.

✅ Check: `ssh -i ~/.ssh/labsuser.pem ubuntu@<public_ip>` works. If you set `alarm_email`, confirm the SNS subscription email.
➡️ Now set the GitHub environment variable `APP_URL` = `http://<public_ip>`.

## Phase 5 · Configure with Ansible (05 → 06)

1. **Edit `deploy/ansible/group_vars/all/main.yml`**:
   - `github_repo: "<you>/specforge"`
   - `ghcr_owner: "<you>"` (lowercase)
2. **Get a runner registration token**: repo → *Settings → Actions → Runners → New self-hosted runner* → copy the token from the `./config.sh --token XXXX` line. **It is valid for 1 hour.**
3. **Create the encrypted secrets file**:
   ```bash
   cd deploy/ansible
   cp group_vars/all/vault.yml.example group_vars/all/vault.yml
   # fill in: vault_postgres_password (openssl rand -hex 16), vault_jwt_secret (openssl rand -hex 32),
   #          vault_grafana_admin_password, vault_github_runner_token,
   #          and vault_ghcr_pull_token if your packages are private
   ansible-vault encrypt group_vars/all/vault.yml
   ```
4. **Run the playbook**:
   ```bash
   ansible all -m ping                       # connectivity check
   ansible-playbook site.yml --ask-vault-pass
   ```
   Roles, in order:
   - `common`: patches, fail2ban, unattended upgrades, SSH hardening, sysctl, swap
   - `docker`: Docker Engine and Compose, plus log rotation
   - `k3s`: single-node Kubernetes with Traefik ingress and local-path storage
   - `cloudwatch`: CloudWatch agent shipping api, worker, web and syslog logs plus memory and disk metrics
   - `github_runner`: registers the self-hosted runner with label `specforge-ec2` as a systemd service
   - `app`: creates the k8s Secrets, applies `deploy/k8s/overlays/aws` (app + Prometheus + Grafana + node-exporter + backup CronJobs), waits for rollouts, runs a smoke test

   The playbook is idempotent, so re-running it is safe. Use `--tags app` to re-apply only the manifests.

✅ Check:
- `http://<public_ip>/` shows the login page.
- *Settings → Actions → Runners* shows `specforge-ec2` as **Idle**.
- The deploy job that was queued in Phase 2 now runs and goes green.

## Phase 6 · Everyday delivery loop (the CI/CD you demo)

```bash
git switch -c feature/better-risks
# ...change code...
git push -u origin feature/better-risks       # open a PR → backend/frontend/iac/scan run
# teammate approves → merge to main
```

On merge, the pipeline runs: **lint/test/SAST + Alembic migration checks on Postgres → Trivy → end-to-end test of the real images in Docker Compose → build (tag = commit SHA) → Trivy image scan → push to GHCR → deploy on EC2 (`kubectl apply -k` of the repo's overlay, so manifest changes ship too) → database migrations (init container) → rolling update → smoke tests → automatic `kubectl rollout undo` if anything fails.** Grafana's "Running build" panel then shows the new commit SHA.

**Demo the auto-rollback.** On a branch, make `/health` return HTTP 500 in `backend/app/main.py`, then merge. Rollout completes, the smoke test fails, and `deploy.sh` rolls all three deployments back. Show the red job log and `kubectl -n specforge rollout history deployment/api`. Then revert the change.

## Phase 7 · Verify and monitor (07 → 08)

On the EC2 (`ssh ...`):
```bash
kubectl -n specforge get pods,svc,ingress,cronjobs
kubectl -n monitoring get pods                     # prometheus, grafana, node-exporter
kubectl -n monitoring port-forward svc/prometheus 9090   # then open http://localhost:9090/targets via ssh -L 9090:localhost:9090
kubectl -n specforge logs deploy/api --tail=50
kubectl -n specforge rollout history deployment/api
curl -s localhost/health && curl -s localhost/ready
```

From anywhere:
```bash
bash scripts/smoke_test.sh http://<public_ip>
```

**Grafana:** `http://<public_ip>/grafana` (anonymous read-only, or `admin` + `vault_grafana_admin_password`). The provisioned *SPECForge · Overview* dashboard shows the deployed commit, request rate, p50/p95/p99 latency, 5xx ratio, jobs, queue backlog, quality scores per project, findings, stale items, and node CPU/memory/disk. Prometheus evaluates 7 alert rules (`deploy/k8s/monitoring/files/alerts.yml`).

In the AWS console: **CloudWatch → Dashboards → `specforge`** (CPU, memory and disk, API 5xx, queue backlog, recent errors) and **Alarms**. Logs are under `/specforge/api`, `/specforge/worker`, `/specforge/web` and `/specforge/system`.
Backups: **S3 → specforge-app-… → backups/postgres/** (nightly at 02:00 IST). To test now: `kubectl -n specforge create job --from=cronjob/pg-backup backup-now`.

**Restore a backup:**
```bash
aws s3 cp s3://<bucket>/backups/postgres/<file>.dump /tmp/restore.dump
kubectl -n specforge cp /tmp/restore.dump postgres-0:/tmp/restore.dump
kubectl -n specforge exec postgres-0 -- pg_restore -U specforge -d specforge --clean --if-exists /tmp/restore.dump
```

## Phase 8 · “Rebuild from nothing” demo

```bash
terraform destroy          # everything gone
terraform apply            # new VPC/EC2/S3 (new IP → update APP_URL)
terraform output -raw ansible_inventory > ../ansible/inventory.ini
ansible-playbook site.yml --ask-vault-pass   # needs a fresh runner token
```

The environment comes back from code. Data comes back from an S3 backup (copy it to the new bucket first, because `force_destroy` empties the old one).

---

## Learner Lab realities (read before your demo)

- **Sessions end after about 4 hours.** EC2 instances are *stopped* (not deleted) and start again with **Start Lab**. The Elastic IP keeps the same address, and k3s, the runner and the CloudWatch agent come back as systemd services. Give it about 2 minutes after the lab starts.
- **Credits are limited.** A `t3.large` costs about $0.08/h. Click **End Lab** when you are done so the instance stops.
- **IAM is locked.** You cannot create roles or users, which is why the design reuses `LabInstanceProfile` and never stores AWS keys in GitHub.
- **Regions:** use `us-east-1`. If an apply fails with `AccessDenied` on one resource (labs differ), comment that resource out, re-apply, and mention it in the report.
- **No EKS**, which is why the cluster is k3s on EC2. It exposes the same Kubernetes API, so Deployments, Services, Ingress, rolling updates and `kubectl` all work the same.

## Optional extras

**Real LLM instead of the offline generator.** Set these in `group_vars/all/main.yml` and put the key in the vault, then run `ansible-playbook site.yml --tags app --ask-vault-pass`:

| Provider | `llm_provider` | `llm_base_url` | `llm_model` |
|---|---|---|---|
| Groq (free tier) | `openai` | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| Google Gemini | `openai` | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-2.0-flash` |
| OpenAI | `openai` | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Anthropic | `anthropic` | `https://api.anthropic.com/v1` | a current Claude model id |

If the model returns invalid JSON twice, SPECForge falls back to the offline generator, and the job result says so.

**Transformer ML layer** (sentence-transformers + NLI cross-encoder, CPU only): in `.github/workflows/ci-cd.yml` add `WITH_ML=true` to the api image `build-args`, and set `USE_TRANSFORMER_MODELS: "true"` in `deploy/k8s/configmap.yaml`. The image grows to about 1.5 GB and the worker needs about 1.5 GiB of RAM; models download on first use.

**HTTPS.** Create a free DuckDNS name pointing at the Elastic IP. Set `domain` and `letsencrypt_email` in `group_vars/all/main.yml`, then run `ansible-playbook site.yml --tags app --ask-vault-pass`. Ansible drops a Traefik `HelmChartConfig` with a Let's Encrypt resolver into k3s and switches both ingresses (app and Grafana) to TLS with an HTTP→HTTPS redirect. Update `APP_URL` to `https://<name>.duckdns.org`.

**Plan B: no AWS available on demo day.** `scripts/local-k8s.sh up` (needs Docker, [k3d](https://k3d.io) and kubectl) builds the images, creates a local k3s cluster, and deploys `deploy/k8s/overlays/local`. That's the *same* manifests as production plus Prometheus and Grafana. Open http://localhost:8081 and http://localhost:8081/grafana. `scripts/local-k8s.sh rollout` demos a rolling update; `down` removes it.

**Compose with monitoring:** `docker compose --profile monitoring up --build` gives the app on :8080, Grafana on :3000 (admin/admin) and Prometheus on :9090.

**Docker Swarm (interim cluster).** On any Docker host: follow the header of `docker-stack.yml` (`docker swarm init`, create three secrets, `docker stack deploy`).

## Troubleshooting

| Symptom | Fix |
|---|---|
| Deploy job stuck “Waiting for a runner” | The lab is stopped or the runner is offline: Start Lab, wait about 2 min, check `systemctl status actions.runner.*` |
| API pod stuck in `Init:0/1` | The `migrate` init container is waiting for Postgres or failing: `kubectl -n specforge logs deploy/api -c migrate` |
| Grafana shows "No data" | `kubectl -n monitoring logs deploy/prometheus`; check http://localhost:9090/targets (port-forward). The API pods need the `prometheus.io/scrape` annotation (already in `base/api.yaml`). |
| Pods in `ImagePullBackOff` | Packages are private and there is no or a wrong `vault_ghcr_pull_token`, or `ghcr_owner` is not lowercase |
| `ExpiredToken` from Terraform | Learner Lab session rotated: copy new credentials into `~/.aws/credentials` |
| Runner registration fails | The token expired (1 h): generate a new one and re-run `--tags runner` |
| `/ready` returns 503 | Postgres not ready: `kubectl -n specforge logs statefulset/postgres` |
| No logs in CloudWatch | `sudo systemctl status amazon-cloudwatch-agent`; check `/opt/aws/amazon-cloudwatch-agent/logs/` |
| Backup CronJob `AccessDenied` | The lab role lacks S3 write on that bucket. Check the bucket name in the ConfigMap. IMDS hop limit must be 2 (set by Terraform). |
