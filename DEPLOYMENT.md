# Deploying the AI Code Reviewer Hosted Backend

This guide walks you through deploying `ai-review-server` so that team members
can use `ai-code-review` without their own Groq API key.

---

## Prerequisites

- A [Groq API key](https://console.groq.com/keys)
- A GitHub repository with this codebase
- A cloud platform account (Render, Railway, or Fly.io)

---

## Option A — Render (Recommended)

### 1. Push the Docker image

Render can build directly from the `Dockerfile` in this repository.

1. Go to [dashboard.render.com](https://dashboard.render.com) and click **New +** > **Web Service**.
2. Connect your GitHub repository (`epicnellson/ai-code-reviewer`).
3. Configure:
   - **Runtime:** Docker
   - **Dockerfile Path:** `./Dockerfile`
   - **Instance Type:** Starter ($7/mo) or higher
4. Add environment variables under **Environment**:

   | Key | Value |
   |---|---|
   | `GROQ_API_KEY` | `gsk_...` (your Groq key) |
   | `AI_REVIEW_API_TOKEN` | *(optional)* a shared secret for client auth |
   | `AI_REVIEW_HOST` | `0.0.0.0` |
   | `AI_REVIEW_PORT` | `8000` |

5. Click **Create Web Service**. Render builds the Docker image and starts the
   server. The first build takes 2–4 minutes.

6. Once live, copy the public URL (e.g. `https://ai-review-server.onrender.com`).

### 2. Blueprint deployment (alternative)

This repo includes a `render.yaml` blueprint. You can import it directly:

1. Go to **New +** > **Blueprint**.
2. Connect the repo — Render reads `render.yaml` automatically.
3. Fill in the `GROQ_API_KEY` value in the environment variables dialog.
4. Deploy.

---

## Option B — Railway

1. Go to [railway.app](https://railway.app) and click **New Project** > **Deploy from GitHub repo**.
2. Select the repository. Railway detects the `Dockerfile` automatically.
3. Open **Variables** and add:

   | Key | Value |
   |---|---|
   | `GROQ_API_KEY` | `gsk_...` |
   | `AI_REVIEW_API_TOKEN` | *(optional)* |
   | `AI_REVIEW_HOST` | `0.0.0.0` |
   | `AI_REVIEW_PORT` | `8000` |

4. Railway builds and deploys. Click **Settings** > **Networking** > **Generate Domain**
   to get a public URL like `ai-review-server.up.railway.app`.

---

## Option C — Fly.io

1. Install the Fly CLI: `curl -L https://fly.io/install.sh | sh`
2. Authenticate: `fly auth login`
3. From the repo root, launch the app:

   ```bash
   fly launch --name ai-review-server --dockerfile Dockerfile
   ```

4. Set secrets:

   ```bash
   fly secrets set GROQ_API_KEY=gsk_... AI_REVIEW_API_TOKEN=my-secret
   ```

5. Deploy:

   ```bash
   fly deploy
   ```

6. The app is available at `https://ai-review-server.fly.dev`.

---

## Option D — Local Docker

Build and run on any machine with Docker installed:

```bash
docker build -t ai-code-review-server .
docker run -d -p 8000:8000 \
  -e GROQ_API_KEY=gsk_... \
  -e AI_REVIEW_API_TOKEN=my-secret \
  --name ai-review-server \
  ai-code-review-server
```

---

## Step 3 — Update `DEFAULT_HOSTED_API_URL`

Once your server is live, update the fallback URL so clients connect
automatically:

1. Open `reviewer/analyzer.py`.
2. Change the constant on line 30:

   ```python
   DEFAULT_HOSTED_API_URL = "https://ai-review-server.onrender.com"
   ```

3. Commit and push:

   ```bash
   git add reviewer/analyzer.py
   git commit -m "chore: set DEFAULT_HOSTED_API_URL to production server"
   git push
   ```

---

## Step 4 — Verify the Deployment

### cURL

```bash
curl https://ai-review-server.onrender.com/health
```

Expected response:

```json
{"status":"ok","service":"ai-code-reviewer"}
```

If you set `AI_REVIEW_API_TOKEN`, include it:

```bash
curl -H "Authorization: Bearer my-secret" \
     https://ai-review-server.onrender.com/health
```

### PowerShell

```powershell
Invoke-RestMethod -Uri "https://ai-review-server.onrender.com/health"
```

With bearer token:

```powershell
$headers = @{ "Authorization" = "Bearer my-secret" }
Invoke-RestMethod -Uri "https://ai-review-server.onrender.com/health" -Headers $headers
```

### Python

```python
import urllib.request, json

url = "https://ai-review-server.onrender.com/health"
resp = urllib.request.urlopen(url)
print(json.loads(resp.read()))
# → {"status": "ok", "service": "ai-code-reviewer"}
```

---

## Step 5 — Client Usage

Once `DEFAULT_HOSTED_API_URL` is set and pushed, team members run reviews
with zero configuration:

```bash
pip install ai-code-checker
ai-code-review --file src/app.py
ai-code-review --diff HEAD~1 --ci
```

To point at a custom or self-hosted server instead:

```bash
export AI_REVIEW_API_URL=https://my-other-server.example.com
export AI_REVIEW_API_TOKEN=optional-secret
ai-code-review --file src/app.py
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Server is currently busy or unreachable` | Check the server logs on your platform. The default server may be cold-starting (Render free tier sleeps after inactivity). |
| `HTTP 401 Unauthorized` | Client is sending a token the server does not expect, or `AI_REVIEW_API_TOKEN` was set on the server but the client does not have it. |
| `HTTP 429 Too Many Requests` | Rate limit hit (30 req/min). Wait or increase limits in `server.py`. |
| Docker build fails on network timeout | Use the `.docker-wheels/` strategy (pre-download wheels) — see `Dockerfile` in this repo. |
