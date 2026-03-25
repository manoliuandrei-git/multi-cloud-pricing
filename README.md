# Multi-Cloud Pricing Calculator

Compare cloud service pricing across **AWS**, **Azure**, **GCP**, and **Oracle Cloud (OCI)** — powered by Claude AI.

## Architecture

```
multi-cloud-pricing/
├── backend/        Python · FastAPI · Oracle DB · Claude agents
└── frontend/       TypeScript · Next.js 14 · Tailwind CSS · Vercel
```

The Next.js frontend calls the FastAPI backend via `/api/backend/*` rewrites. In production, the backend runs separately (e.g. on a VM or container) and Vercel proxies to it.

## Quick Start

### 1. Backend

```bash
cd backend
cp ../.env.template .env          # fill in credentials
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Swagger docs at `/docs`.

### 2. Frontend

```bash
cd frontend
cp .env.local.template .env.local  # set BACKEND_URL=http://localhost:8000
npm install
npm run dev
```

Open `http://localhost:3000`.

## Backend API

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/health` | Liveness check |
| `GET`  | `/api/config` | Categories & providers |
| `POST` | `/api/compare` | Main comparison (map + AI + cost estimate) |
| `POST` | `/api/refresh` | Trigger pricing data refresh |
| `GET`  | `/api/refresh/status` | Check if refresh is needed |

### Example `/api/compare` request

```json
{
  "user_input": "PostgreSQL database for production",
  "categories": ["Database"],
  "providers": ["AWS", "Azure", "OCI"],
  "specifications": {
    "vcpu": 4,
    "memory_gb": 16,
    "storage_gb": 100
  }
}
```

## Deploying to Vercel

1. Push to GitHub: `git remote add origin https://github.com/manoliu-andrei/multi-cloud-pricing.git`
2. Import the repo in [vercel.com](https://vercel.com)
3. Set `BACKEND_URL` environment variable to your FastAPI deployment URL
4. Update `vercel.json` → `rewrites.destination` with the same URL

## Environment Variables

Copy `.env.template` to `.env` in the `backend/` directory and fill in:

- `ATP_PASSWORD` — Oracle Autonomous Database password
- `ANTHROPIC_API_KEY` — Anthropic API key
- `OCI_BUCKET_NAME` / `OCI_NAMESPACE` — OCI Object Storage for PDF pricing files
