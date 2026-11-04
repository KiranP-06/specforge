# ADR 0001: k3s on a single EC2 instance instead of EKS

**Status:** accepted

## Context
The project must demonstrate Kubernetes on AWS. AWS Academy Learner Lab restricts IAM (no role creation), rotates credentials every session, and has a small credit budget. An EKS control plane costs about $0.10/h before any nodes, and it needs IAM roles we cannot create.

## Decision
Run **k3s** (a CNCF-certified Kubernetes distribution) on one `t3.large` EC2 instance provisioned by Terraform and configured by Ansible. Use the built-in Traefik ingress and local-path storage.

## Consequences
- The same Kubernetes API and manifests (Deployments, StatefulSet, Services, Ingress, CronJobs, rolling updates, `kubectl rollout undo`).
- A single node means no high availability. That is acceptable for a lab, and the manifests would move to a multi-node cluster or EKS unchanged (only `storageClassName` and the ingress class would need changing).
- Deploys run from a **self-hosted GitHub runner on the node**, so no AWS credentials are stored in GitHub.
