# SPECForge Recovery Guide

How to bring the live site back by yourself. Start at **Level 1** and only go to the next level if the current one does not fix it.

| Thing | Value |
|---|---|
| Site | http://44.208.73.1 (health: http://44.208.73.1/health) |
| Grafana | http://44.208.73.1/grafana |
| SSH | `ssh -i ~/.ssh/labsuser.pem ubuntu@44.208.73.1` |
| Repo | https://github.com/KiranP-06/specforge |
| State bucket / app bucket | `specforge-tfstate-00991f` / `specforge-app-00991f` |
| Project folder on the Mac | `~/Downloads/specforge` |

**Site is healthy when** `/health` shows `"status":"ok"` and this passes on your Mac:
```bash
cd ~/Downloads/specforge && bash scripts/smoke_test.sh http://44.208.73.1
```

---

## Two things you will need often

### A. Fresh AWS credentials (every time you click Start Lab)
1. AWS Academy → Learner Lab → **AWS Details** → **AWS CLI: Show** → copy the whole block.
2. In Terminal, open the credentials file:
   ```bash
   nano ~/.aws/credentials
   ```
   Press **Ctrl+K** until the file is empty, then **Cmd+V** to paste. Save with **Ctrl+O**, **Enter**, then **Ctrl+X**.
3. Check it works:
   ```bash
   aws sts get-caller-identity
   ```
   The `Arn` must contain `voclabs`. If you see `ExpiredToken`, repeat this section.

### B. Allow SSH from your current network (when `ssh` says "Operation timed out")
SSH only accepts one IP address. When your network changes (flat, college, hotspot), update it:
```bash
cd ~/Downloads/specforge/deploy/terraform && sed -i '' "s#^admin_cidr.*#admin_cidr  = \"$(curl -4 -s ifconfig.me)/32\"#" terraform.tfvars && terraform plan -out tfplan
```
The plan must say **1 to change, 0 to destroy**. Only then:
```bash
terraform apply tfplan
```
College Wi-Fi often blocks SSH completely; use your **phone hotspot** instead.

---

## Level 1: Start the lab and wait (fixes 95% of cases)
1. AWS Academy → **Start Lab** → wait for the **green dot**.
2. Wait **3 to 5 minutes**. The EC2 boots, then k3s, the app, the runner and the CloudWatch agent start by themselves.
3. Open http://44.208.73.1/health. If it shows `"status":"ok"`, you are done.

## Level 2: The EC2 is not running
1. AWS Console → **EC2 → Instances** → find `specforge-k3s`.
2. If it is **Stopped**: select it → **Instance state → Start instance**. Wait 3 to 5 minutes, then check `/health`.
3. If it is **Terminated** or missing, go to **Level 6**.

## Level 3: EC2 is running but the site is down
SSH in (if it times out, do section **B** first):
```bash
ssh -i ~/.ssh/labsuser.pem ubuntu@44.208.73.1
```
Check that k3s is running:
```bash
sudo systemctl status k3s --no-pager | head -5
```
If it does not say `active (running)`:
```bash
sudo systemctl restart k3s
```
Wait 2 minutes, then look at the pods:
```bash
sudo k3s kubectl get pods -A
```
Everything should be `Running` (or `Completed` for jobs). If an app pod is stuck, restart the app:
```bash
sudo k3s kubectl -n specforge rollout restart deployment/api deployment/worker deployment/web
```
Then check again from the Mac with the smoke test. Common pod problems:

| Pod status | Meaning / fix |
|---|---|
| `ImagePullBackOff` | GitHub packages must be **public** (github.com/KiranP-06?tab=packages → each package → Package settings → visibility). |
| `Init:0/1` on api | Database not ready: `sudo k3s kubectl -n specforge logs deploy/api -c migrate` |
| `Pending` | Disk or memory full: `df -h` and `free -h` |
| `helm-install-traefik` in `CrashLoopBackOff` | Ingress missing. Go to **Level 4**. |

Type `exit` to leave the server.

## Level 4: Re-apply everything with Ansible (safe to run any time)
This re-checks the whole server and redeploys the app. It never deletes your data. You need your **vault password**.
```bash
cd ~/Downloads/specforge/deploy/ansible && ansible-playbook site.yml --ask-vault-pass
```
Success = the last line shows **`failed=0`**. To redeploy only the app (faster):
```bash
ansible-playbook site.yml --tags app --ask-vault-pass
```
If it fails with `UNREACHABLE`, do section **B**. If it fails at the runner task, do **Level 5**.

## Level 5: GitHub runner is offline (deploys stay "Waiting for a runner")
Check: repo → **Settings → Actions → Runners**. `specforge-ec2` should be **Idle**.

**5a. Just restart it** (SSH in first):
```bash
sudo systemctl restart actions.runner.KiranP-06-specforge.specforge-ec2.service
```
Wait 30 seconds and refresh the Runners page.

**5b. The runner disappeared from GitHub** (GitHub removes runners that were offline for about 14 days). Register it again:
1. On the server, remove the old registration files:
   ```bash
   sudo rm -f /home/runner/actions-runner/.runner /home/runner/actions-runner/.credentials /home/runner/actions-runner/.credentials_rsaparams
   ```
   Then `exit`.
2. Get a new token: https://github.com/KiranP-06/specforge/settings/actions/runners/new → copy only the string after `--token` (valid **1 hour**).
3. Put it in the vault on the Mac. This opens an editor; replace the value of `vault_github_runner_token`, then save and exit:
   ```bash
   cd ~/Downloads/specforge/deploy/ansible && ansible-vault edit group_vars/all/vault.yml
   ```
4. Register and restart:
   ```bash
   ansible-playbook site.yml --tags runner --ask-vault-pass
   ```
   ```bash
   ssh -i ~/.ssh/labsuser.pem ubuntu@44.208.73.1 'sudo systemctl restart actions.runner.KiranP-06-specforge.specforge-ec2.service'
   ```
5. Re-run any waiting deploy: GitHub → **Actions** → the run → **Re-run failed jobs**.

## Level 6: Everything is gone (lab was reset, EC2 terminated)
Rebuild from code. Takes about 30 minutes. Do section **A** first.

1. **Check the buckets still exist:**
   ```bash
   aws s3 ls | grep specforge
   ```
   If both are missing, create new ones (pick any new suffix, e.g. today's date):
   ```bash
   aws s3api create-bucket --bucket specforge-tfstate-NEWSUFFIX
   ```
   ```bash
   aws s3api put-bucket-versioning --bucket specforge-tfstate-NEWSUFFIX --versioning-configuration Status=Enabled
   ```
   ```bash
   aws s3api create-bucket --bucket specforge-app-NEWSUFFIX
   ```
   Then edit `deploy/terraform/backend.hcl` (`bucket = ...`) and `deploy/terraform/terraform.tfvars` (`app_bucket = ...`) to the new names, and delete the old local Terraform cache:
   ```bash
   cd ~/Downloads/specforge/deploy/terraform && rm -rf .terraform
   ```
2. **Create the infrastructure:**
   ```bash
   cd ~/Downloads/specforge/deploy/terraform && terraform init -reconfigure -backend-config=backend.hcl && terraform plan -out tfplan
   ```
   Read the plan, then:
   ```bash
   terraform apply tfplan
   ```
   ```bash
   terraform output -raw ansible_inventory > ../ansible/inventory.ini && terraform output public_ip
   ```
3. **New IP?** Update GitHub: repo → Settings → Environments → `production` → variable `APP_URL` = `http://<new ip>`. Use the new IP everywhere in this guide.
4. **New runner token** (Level 5b steps 2 to 3), then configure the server:
   ```bash
   cd ~/Downloads/specforge/deploy/ansible && ansible-playbook site.yml --ask-vault-pass
   ```
5. **Restore the database** (only if you saved a backup to `~/specforge-backups`). Copy it to the server, then into Postgres:
   ```bash
   scp -i ~/.ssh/labsuser.pem ~/specforge-backups/<file>.dump ubuntu@<ip>:/tmp/restore.dump
   ```
   ```bash
   ssh -i ~/.ssh/labsuser.pem ubuntu@<ip> 'sudo k3s kubectl -n specforge cp /tmp/restore.dump postgres-0:/tmp/restore.dump && sudo k3s kubectl -n specforge exec postgres-0 -- pg_restore -U specforge -d specforge --clean --if-exists /tmp/restore.dump'
   ```
6. Check with the smoke test.

---

## Emergency: AWS unavailable during a demo (Plan B, on the Mac)
Open Docker Desktop and wait for "Engine running", then:
```bash
cd ~/Downloads/specforge && bash scripts/local-k8s.sh up
```
Open http://localhost:8081 and http://localhost:8081/grafana. These are the same Kubernetes manifests as production. (Always start the script with `bash`; macOS blocks running it directly.)

---

## Keep these safe (not in git, needed for recovery)
- The **vault password** (password manager)
- `~/.ssh/labsuser.pem`
- `deploy/ansible/group_vars/all/vault.yml` (encrypted)
- `deploy/terraform/terraform.tfvars` and `deploy/terraform/backend.hcl`
- A recent database backup:
  ```bash
  mkdir -p ~/specforge-backups && aws s3 cp s3://specforge-app-00991f/backups/postgres/ ~/specforge-backups/ --recursive
  ```

## Never do
- Click **Reset** in Learner Lab (deletes everything)
- Run `terraform destroy` unless you really want to delete the server
- Push to `main` while the lab is off (the deploy waits for the runner and GitHub cancels it after 24 hours)
- Leave the `demo/broken-health` change merged in `main` (undo with `git revert -m 1 --no-edit <merge commit>` and push)
