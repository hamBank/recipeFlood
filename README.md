# Recipe Flood

A recipe hub — 321 recipes imported from twelve years of an Australian food
blog, plus manual entry and AI-assisted import from a photo or a paste.

**Production:** <https://recipeflood.hups.club>

## What's interesting about it

- **A master ingredient list.** Price, density and per-100g nutrition live
  once per pantry item; every recipe that uses it picks them up.
- **Automatic weight conversion.** Recipes are written in cups and spoons,
  costs and nutrition need grams. The converter records *how* it got each
  weight, so an estimate is never mistaken for a measurement. Measures are
  Australian — 250ml cup, **20ml tablespoon**.
- **A reproducible import.** Feed snapshot → structured JSON → database,
  all committed, all idempotent. The collection rebuilds from this repo
  with no API key.
- **Honest panels.** Nutrition reports the share of the recipe's weight it
  could account for; cost reports how many ingredients had a price. No
  confident-looking undercounts.

## Docs

| | |
|---|---|
| [SPEC.md](SPEC.md) | What it does, and why the model looks like it does |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Stack, repo layout, conventions |
| [DATA_MODEL.md](DATA_MODEL.md) | Tables and schemas |
| [API.md](API.md) | Endpoints and access levels |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Local setup, and running the blog import |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Server, deploy, OAuth, backups |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python scripts/seed_categories.py
python -m scripts.load_snapshot --heuristic     # 321 recipes, no API key needed

AUTH_ENABLED=false python -m uvicorn backend.main:app --reload
cd frontend && npm install && npm run dev       # → http://localhost:5173
```

## Stack

FastAPI · SQLModel · Alembic · Postgres (SQLite locally) · React 19 · Vite ·
Tailwind 4 · Anthropic API — the same shape as its sibling apps
[pocketMoney](https://github.com/hamBank/pocketMoney) and travelCompantion.
