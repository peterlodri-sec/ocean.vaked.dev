# AGENTS.md — `ocean.vaked.dev`

> **Sovereign High-Compute Hub, Model Ocean & Distributed Memory for the vaked.dev Constellation**

`ocean.vaked.dev` is the dedicated compute instance providing unmetered 1.58-bit / ternary model inference, MEM8 associative wave memory recall, autonomous agent scheduling, and 432Hz spatial audio streaming.

---

## ✦ Services & Ports

- **Frontend & Telemetry**: Cloudflare Pages (`ocean-vaked-dev`) / `https://ocean.vaked.dev/`
- **Model Ocean API**: `:8000` (`/v1/models`, `/v1/chat/completions`)
- **Memory Ocean Recall**: `:8000` (`/memory/recall`, `/memory/ingest`)
- **Swarm Factory**: `server/agent_factory.py`

---

## ✦ Deploying Frontend to Cloudflare Pages

```bash
npm run deploy    # Deploys static UI to Cloudflare Pages (ocean-vaked-dev)
```

## ✦ Deploying Compute Server (Docker / NixOS)

```bash
docker-compose up -d --build
```

*the constellation · 0 + 1 · fine touch from within · vaked.dev*
