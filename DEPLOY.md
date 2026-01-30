# Deploy zhaku.eu to Railway (from GitHub)

## 1. Push your code to GitHub

From your project folder (e.g. `c:\Users\user\Desktop\bg web`):

```bash
cd "c:\Users\user\Desktop\bg web"

git init
git add .
git commit -m "Initial commit - zhaku.eu car photo processor"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
git push -u origin main
```

If the repo already exists and you only need to push updates:

```bash
cd "c:\Users\user\Desktop\bg web"
git add .
git commit -m "Your commit message"
git push origin main
```

Replace `YOUR_USERNAME` and `YOUR_REPO_NAME` with your GitHub username and repository name.

---

## 2. Deploy on Railway

1. Go to **[railway.app](https://railway.app)** and sign in (GitHub login is fine).
2. **New Project** → **Deploy from GitHub repo** → select your repository.
3. Railway will detect the `Dockerfile` and build the app.
4. Open the service → **Variables** and add:

| Variable | Value | Required |
|----------|--------|----------|
| `APP_SECRET` | Any long random string (e.g. `openssl rand -hex 32`) | Yes |
| `ADMIN_PASSWORD` | Password for `/admin` | Yes |
| `PUBLIC_BASE_URL` | `https://YOUR-APP.up.railway.app` (see Railway **Settings → Domains**) | Yes |
| `CORS_ORIGINS` | `*` (or `https://zhaku.eu,https://www.zhaku.eu` if frontend is on zhaku.eu) | Yes if frontend on another domain |
| `API_KEY` | Optional: e.g. `your-secret` if you use Bearer auth from frontend | No |

5. **Settings → Generate Domain** if you don’t have one yet. Use that URL as `PUBLIC_BASE_URL`.
6. Redeploy if you changed variables (e.g. **Deploy → Redeploy**).

---

## 3. After deploy

- App URL: `https://YOUR-APP.up.railway.app`
- Health check: `https://YOUR-APP.up.railway.app/health` → `{"status":"ok"}`
- Admin: `https://YOUR-APP.up.railway.app/admin` (use `ADMIN_PASSWORD`)

If your **frontend** is on zhaku.eu (different domain), set in your frontend HTML (before loading `app.js`):

```html
<script>
  window.API_BASE_URL = "https://YOUR-APP.up.railway.app";
  // window.API_KEY = "your-secret";  // only if you set API_KEY on Railway
</script>
```

---

## Quick reference – Git commands

```bash
# First time (create repo on GitHub first, then):
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main

# Later updates (deploy = push to main):
git add .
git commit -m "Fix app / update feature"
git push origin main
```

Railway will redeploy automatically on every push to `main`.
