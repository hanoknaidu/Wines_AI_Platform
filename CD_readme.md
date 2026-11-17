# CD Plan: Wines AI on AKS (minimal, not production)

This is a **to-do list**, not a pipeline. It lists the smallest set of Azure
resources and steps needed to run Wines AI (backend + frontend) on an AKS
cluster, and then what the CD pipeline will automate once the manual path works.

Every resource step shows two ways to do it:
- **CLI**: `az` commands (Azure CLI, run in a terminal / CMD)
- **Portal**: the Azure web interface at https://portal.azure.com

> Scope: one environment, one small node, plain HTTP on a public IP, no custom
> domain, no TLS, no monitoring. Good enough to see the app running in AKS.

---

## What we are deploying

| Component | Image | Port | Notes |
|---|---|---|---|
| backend  | `wines-ai-backend`  | 8010 | FastAPI. **Must run as 1 replica**: SQLite + in-process SSE bus. Needs a writable volume at `/data`. Health: `/api/v1/healthz`, ready: `/api/v1/readyz`. |
| frontend | `wines-ai-frontend` | 8080 | nginx serving the Vite build; proxies `/api` to `BACKEND_ORIGIN` (default `http://backend:8010`, so the backend Service must be named `backend`). |

Runtime config the backend needs (see [backend/.env.docker.example](backend/.env.docker.example)):

| Variable | Value for this setup | Secret? |
|---|---|---|
| `WA_COOKIE_SECRET` | random string (`python3 -c "import secrets; print(secrets.token_urlsafe(48))"`) | **yes** |
| `WA_COOKIE_SECURE` | `false` (we are on plain HTTP; otherwise the session cookie is dropped) | no |
| `WA_CORS_ORIGINS` | `["http://<frontend-public-ip>"]` | no |
| `WA_ENGINE` / `WA_LLM_PROVIDER` | `deterministic` / `offline` to start ($0, no key) | no |
| `WA_ANTHROPIC_API_KEY` | only if/when we switch to `anthropic` (image must be built with `EXTRAS="orchestrator"`) | **yes** |

---

## Naming used below (change once, reuse everywhere)

```bash
LOCATION=eastus
RG=rg-winesai-dev
ACR=acrwinesaidev        # globally unique, lowercase letters/digits only, 5-50 chars
AKS=aks-winesai-dev
NS=wines-ai
```

Windows CMD uses `set RG=rg-winesai-dev` and `%RG%` instead of `$RG`.

---

## To-do list

### [ ] 1. Create an Azure account and subscription

**Portal**
1. Go to https://azure.microsoft.com/free and sign up (free account gives credit for 30 days), or use an existing subscription.
2. Note the **Subscription** name/ID under *Subscriptions*.

**CLI** (install the CLI first: `brew install azure-cli` on macOS, or the MSI on Windows)
```bash
az login
az account list -o table
az account set --subscription "<subscription-id>"
```

Register the providers AKS and ACR need (one-time per subscription; the Portal does this automatically):
```bash
az provider register --namespace Microsoft.ContainerService
az provider register --namespace Microsoft.ContainerRegistry
```

---

### [ ] 2. Create a Resource Group

A folder that holds everything below. Deleting it deletes all of it (handy for cleanup).

**CLI**
```bash
az group create --name $RG --location $LOCATION
```

**Portal**
1. Search **Resource groups** → **+ Create**.
2. Subscription: yours · Resource group: `rg-winesai-dev` · Region: `East US`.
3. **Review + create** → **Create**.

---

### [ ] 3. Create the Azure Container Registry (ACR)

Holds the two Docker images.

**CLI**
```bash
az acr create --resource-group $RG --name $ACR --sku Basic
```

**Portal**
1. Search **Container registries** → **+ Create**.
2. Resource group: `rg-winesai-dev` · Registry name: `acrwinesaidev` · Location: `East US` · Pricing plan: **Basic**.
3. **Review + create** → **Create**.

---

### [ ] 4. Create the AKS cluster (attached to ACR)

One small node is enough. `--attach-acr` lets the cluster pull from ACR without any image-pull secret.

**CLI**
```bash
az aks create \
  --resource-group $RG \
  --name $AKS \
  --tier free \
  --node-count 1 \
  --node-vm-size Standard_B2s \
  --attach-acr $ACR \
  --generate-ssh-keys
```

**Portal**
1. Search **Kubernetes services** → **+ Create** → **Kubernetes cluster**.
2. *Basics*: Resource group `rg-winesai-dev` · Cluster preset **Dev/Test** · Name `aks-winesai-dev` · Region `East US` · Pricing tier **Free**.
3. *Node pools*: edit the system pool → node size **Standard_B2s**, scale method **Manual**, node count **1**.
4. *Integrations*: Container registry → select `acrwinesaidev`.
5. **Review + create** → **Create** (takes ~5-10 min).

> If you created the cluster without attaching ACR: `az aks update -g $RG -n $AKS --attach-acr $ACR`
> (Portal: ACR → *Access control (IAM)* → add role **AcrPull** for the cluster's kubelet identity.)

---

### [ ] 5. Connect `kubectl` to the cluster

**CLI**
```bash
az aks install-cli                       # installs kubectl if missing
az aks get-credentials --resource-group $RG --name $AKS
kubectl get nodes                        # should show 1 node Ready
```

**Portal**: AKS resource → **Connect** shows the same two commands, or use **Cloud Shell** (top bar `>_`) where `az` and `kubectl` are pre-installed.

---

### [ ] 6. Build and push the images to ACR (first time by hand)

**CLI, option A: build in Azure (no local Docker needed)**
```bash
az acr build --registry $ACR --image wines-ai-backend:v1  ./backend
az acr build --registry $ACR --image wines-ai-frontend:v1 ./frontend
```

**CLI, option B: local Docker**
```bash
az acr login --name $ACR
docker build --platform linux/amd64 -t $ACR.azurecr.io/wines-ai-backend:v1  ./backend
docker build --platform linux/amd64 -t $ACR.azurecr.io/wines-ai-frontend:v1 ./frontend
docker push $ACR.azurecr.io/wines-ai-backend:v1
docker push $ACR.azurecr.io/wines-ai-frontend:v1
```
(`--platform linux/amd64` matters on Apple Silicon Macs; AKS nodes are amd64.)

**Portal**: there is no build button; verify the push under ACR → **Repositories** (you should see both repos with tag `v1`).

---

### [ ] 7. Write the Kubernetes manifests (in repo, e.g. `k8s/`)

Minimal set, all in namespace `wines-ai`:

| File | Kind | Purpose |
|---|---|---|
| `namespace.yaml` | Namespace | `wines-ai` |
| `backend-secret` | Secret | `WA_COOKIE_SECRET` (+ later `WA_ANTHROPIC_API_KEY`). Create via CLI, **do not commit**. |
| `backend-config.yaml` | ConfigMap | `WA_COOKIE_SECURE=false`, `WA_CORS_ORIGINS`, `WA_ENGINE`, `WA_LLM_PROVIDER` |
| `backend-pvc.yaml` | PersistentVolumeClaim | 1 Gi, `ReadWriteOnce`, default storage class → mounted at `/data` (SQLite db + ingest store) |
| `backend-deployment.yaml` | Deployment | `replicas: 1`, `strategy: Recreate` (RWO disk + single SQLite writer), probes on `/api/v1/healthz` and `/api/v1/readyz`, `runAsNonRoot`, uid 10001, `fsGroup: 10001` so `/data` is writable |
| `backend-service.yaml` | Service (ClusterIP) | name **`backend`**, port 8010 (internal only) |
| `frontend-deployment.yaml` | Deployment | 1 replica, port 8080 |
| `frontend-service.yaml` | Service (**LoadBalancer**) | port 80 → 8080; this gives the public IP |

No Ingress controller, no cert-manager, no DNS at this stage.

Secret, created by hand:
```bash
kubectl create namespace $NS
kubectl -n $NS create secret generic backend-secret \
  --from-literal=WA_COOKIE_SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"
```
(Portal alternative: AKS resource → **Kubernetes resources → Configuration → Secrets → + Create**.)

---

### [ ] 8. First manual deploy

**CLI**
```bash
kubectl apply -n $NS -f k8s/
kubectl -n $NS get pods -w
kubectl -n $NS get svc frontend          # wait for EXTERNAL-IP
```
Then set `WA_CORS_ORIGINS` in the ConfigMap to `["http://<EXTERNAL-IP>"]`, re-apply, and
`kubectl -n $NS rollout restart deploy/backend`. Open `http://<EXTERNAL-IP>`.

**Portal**: AKS resource → **Kubernetes resources → Workloads → + Create → Apply a YAML**, paste each manifest. Public IP shows under **Services and ingresses**.

---

### [ ] 9. Let GitHub Actions talk to Azure (prerequisite for CD)

Use **OIDC (federated credentials)**: no password stored in GitHub.

**CLI**
```bash
# App registration + service principal
APP_ID=$(az ad app create --display-name gh-winesai-cd --query appId -o tsv)
az ad sp create --id $APP_ID

# Allow GitHub to log in as it from the main branch
az ad app federated-credential create --id $APP_ID --parameters '{
  "name": "gh-main",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:<github-owner>/<repo>:ref:refs/heads/main",
  "audiences": ["api://AzureADTokenExchange"]
}'

# Permissions: push images, deploy to the cluster
ACR_ID=$(az acr show -n $ACR --query id -o tsv)
AKS_ID=$(az aks show -g $RG -n $AKS --query id -o tsv)
az role assignment create --assignee $APP_ID --role AcrPush --scope $ACR_ID
az role assignment create --assignee $APP_ID --role "Azure Kubernetes Service Cluster User Role" --scope $AKS_ID
az role assignment create --assignee $APP_ID --role "Azure Kubernetes Service RBAC Writer" --scope $AKS_ID   # only if AKS uses Azure RBAC; otherwise "Contributor" on $AKS_ID
```

**Portal**
1. **Microsoft Entra ID → App registrations → + New registration** → name `gh-winesai-cd`.
2. In the app: **Certificates & secrets → Federated credentials → + Add** → scenario *GitHub Actions deploying Azure resources* → org, repo, entity **Branch**, `main`.
3. ACR → **Access control (IAM) → + Add role assignment** → **AcrPush** → member: `gh-winesai-cd`.
4. AKS → **Access control (IAM)** → **Azure Kubernetes Service Cluster User Role** (+ RBAC Writer or Contributor) → `gh-winesai-cd`.

Add these as **GitHub repo secrets/variables** (Settings → Secrets and variables → Actions):
`AZURE_CLIENT_ID` (= APP_ID), `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `ACR_NAME`, `AKS_RG`, `AKS_NAME`.

---

### [ ] 10. CD pipeline (plan only; build later)

New workflow `.github/workflows/cd.yml`, triggered when CI succeeds on `main`
(`workflow_run` on `CI`, or `push` to `main`), plus `workflow_dispatch`.

Steps:
1. `azure/login` with OIDC (needs `permissions: id-token: write`).
2. `az acr login`, build + push both images tagged with the **git SHA** (reuse the CI buildx cache).
3. `azure/aks-set-context` to the cluster.
4. `kubectl set image` (or `azure/k8s-deploy`) on `deploy/backend` and `deploy/frontend` with the new SHA tag.
5. `kubectl rollout status` for both; fail the job if either does not become ready.
6. (Optional) curl `http://<EXTERNAL-IP>/api/v1/readyz` as a smoke test.

Secrets (`WA_COOKIE_SECRET`, API key) stay in the cluster Secret; the pipeline never handles them.

---

### [ ] 11. Cleanup / cost control

Everything lives in one resource group, so:
```bash
az aks stop  -g $RG -n $AKS        # pause the node when not in use (stop paying for the VM)
az aks start -g $RG -n $AKS
az group delete --name $RG --yes   # delete everything
```
Portal: AKS resource → **Stop**; or Resource group → **Delete resource group**.

Rough cost while running: 1× Standard_B2s node + ACR Basic + a public IP + a 1 Gi disk; AKS Free tier has no control-plane charge.

---

## Explicitly out of scope for now

TLS / custom domain / Ingress controller · multiple environments (dev/stage/prod) ·
Key Vault (secrets live in a K8s Secret) · Terraform/Bicep · autoscaling ·
Azure Monitor / Log Analytics · backups of the SQLite volume · private cluster / network policies.

## Open questions

1. **Azure region**: `eastus` assumed. Any preference?
2. **LLM mode on AKS**: start `offline` ($0), or deploy with `anthropic` from day one (needs the API key and an image built with `EXTRAS="orchestrator"`)?
3. **CD trigger**: deploy on every merge to `main`, or only manually (`workflow_dispatch`) at first?
4. **Manifests format**: plain YAML (assumed, simplest) or a small Helm chart / Kustomize?
5. **Data persistence**: is losing the SQLite data on a cluster rebuild acceptable for now?
