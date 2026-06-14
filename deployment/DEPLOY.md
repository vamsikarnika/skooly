# Deploying Skooly (smartskool.in)

Cheapest, low-ops production setup:

```
                        Cloudflare (DNS + edge TLS, free)
            ┌───────────────────────────┬─────────────────────────┐
   app.smartskool.in                api.smartskool.in
   (Cloudflare Worker — SSR)        (Cloudflare Tunnel, outbound)
   skooly-stride, free tier                 │
                                     ┌───────▼────────┐  small VM (Hetzner ~$4/mo)
                                     │  cloudflared    │  no inbound ports
                                     │      │          │
                                     │   api:8000      │  Django + gunicorn + WhiteNoise
                                     └───────┬────────┘
                                             ├──▶ Neon Postgres (managed, TLS)
                                             └──▶ Cloudflare R2 (media)
```

The VM runs only **api + cloudflared**. No Postgres, Redis, Caddy, or open ports.

---

## 1. Managed services (one-time)

**Neon (Postgres)** — neon.tech → new project, region near the VM (e.g. Singapore / Mumbai).
Copy the **pooled** connection details (`…-pooler…` host) into `.env.prod` (`DB_*`, `DB_SSLMODE=require`).

**Cloudflare R2 (media)** — Cloudflare dashboard → R2 → create bucket `smartskool-media` →
create an API token (Object Read & Write) → fill `R2_*` (endpoint = `https://<acct>.r2.cloudflarestorage.com`).

**Cloudflare Tunnel (api)** — Zero Trust → Networks → Tunnels → **Create tunnel** (name `smartskool`):
- Copy the **tunnel token** → `CLOUDFLARE_TUNNEL_TOKEN`.
- Add a **Public Hostname**: `api.smartskool.in` → service **`http://api:8000`**.
  (Cloudflare auto-creates the DNS record. cloudflared reaches `api` by its compose service name.)

## 2. The VM (Hetzner CAX11 or similar)

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh

# Firewall: SSH only — the tunnel is outbound, nothing else needs to be open.
ufw default deny incoming && ufw allow OpenSSH && ufw --force enable

# Get the code (backend repo)
git clone https://github.com/vamsikarnika/skooly.git
cd skooly/deployment
cp .env.prod.example .env.prod && nano .env.prod   # fill everything in

# Deploy
chmod +x deploy.sh && ./deploy.sh
```

`deploy.sh` builds the api image and starts `api` + `cloudflared`. On start the api
container runs migrations + `collectstatic`, then gunicorn. `api.smartskool.in` is
live through the tunnel within ~30s.

## 3. Frontend → Cloudflare Workers (skooly-stride)

```bash
cd skooly-stride
echo 'VITE_API_BASE_URL=https://api.smartskool.in' >  .env.production
echo 'VITE_USE_MOCK_API=false'                     >> .env.production
npm install
npm run deploy            # vite build (prod) + wrangler deploy
```

First time, authenticate wrangler (`npx wrangler login`) and add the custom domain:
Cloudflare dashboard → Workers & Pages → your worker → **Custom Domains** →
add `app.smartskool.in` (and optionally redirect root `smartskool.in` → `app.`).

## 4. First admin (no demo data in prod)

`SKOOLY_SEED_DEMO=false`, so the DB starts empty. Create the first school + admin once
via the signup API (then log in at app.smartskool.in):

```bash
curl -X POST https://api.smartskool.in/api/v1/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"schoolName":"…","board":"AP_STATE","phone":"+91…","password":"…","firstName":"…","lastName":"…"}'
```

## Updating / operating

- **Release:** `cd skooly/deployment && ./deploy.sh` (backend); `npm run deploy` (frontend).
- **Logs:** `docker compose -f docker-compose.prod.yml logs -f api`
- **DB backups:** Neon keeps automated backups + PITR — nothing to run.
- ⚠️ **Never** run `docker compose down -v` — though with Neon the DB isn't on this box anyway.
