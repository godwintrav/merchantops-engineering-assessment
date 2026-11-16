# MerchantOps

MerchantOps is a full-stack product and inventory-management application built with **Django, Django REST Framework, MySQL, and Vue 3**.

This repository is supplied for a senior full-stack engineering assessment. **Read [ASSESSMENT.md](ASSESSMENT.md) for the task and submission requirements.**

## Technology stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.12, Django, Django REST Framework |
| Database | MySQL 8.4 |
| Frontend | Vue 3, Vite |
| Development environment | Docker Compose |

## Prerequisites

- Git
- Docker Desktop, or Docker Engine with Docker Compose
- A browser

The app's Python, Node.js, and database services run in containers; you do not need to install those runtimes on your host to start the application.

## Getting started

From the repository root:

```bash
chmod +x setup.sh
./setup.sh
```

The setup script starts MySQL and the Django backend, applies migrations, prepares the sample catalogue and complex product fixtures, provisions a demo operator, configures the local merchant context, and starts the Vue frontend.

**On first setup**, you will be prompted to choose a password for the demo operator. Use a local development password; no shared password is included in this repository. On subsequent setup runs, an existing demo operator's password is preserved.

### Open MerchantOps

| Service | Local URL |
| --- | --- |
| Vue application | http://127.0.0.1:5173/ |
| Django backend | http://127.0.0.1:8002/ |

Sign in with:

- **Username:** `demo_operator`
- **Password:** the password you chose during initial setup

The demo operator belongs to the **Northstar Retail** merchant. The setup script resolves that merchant's database ID and writes local frontend configuration automatically.

## What exists in the application

The starter application includes:

- Product catalogue, search, and pagination.
- Product detail editing.
- Product variants, pricing, inventory, and reservations.
- Sales-channel availability.
- Product activity history.
- Authenticated, merchant-scoped access controls.

See [ASSESSMENT.md](ASSESSMENT.md) for the feature to add and the performance investigation to complete.

## Project layout

```text
.
├── ASSESSMENT.md          # Candidate assignment
├── README.md              # Setup and development guide
├── docker-compose.yml     # MySQL, Django, and Vue services
├── setup.sh               # Repeatable local provisioning
├── backend/
│   ├── catalog/
│   │   ├── management/commands/
│   │   ├── migrations/
│   │   └── tests/
│   ├── pyproject.toml     # Black/isort configuration
│   └── requirements-dev.txt
└── frontend/
    └── src/
```

## Running the services

Start existing services:

```bash
docker compose up -d
```

Check service status:

```bash
docker compose ps
```

View logs:

```bash
docker compose logs -f backend
docker compose logs -f frontend
```

Stop the services while preserving database data:

```bash
docker compose down
```

**Caution:** `docker compose down -v` deletes named volumes, including the local MySQL database. Avoid it unless you intentionally want to reset the environment.

## Backend development and tests

Run Django commands **inside Docker Compose**, not through a host Python interpreter.

Run the backend catalogue suite:

```bash
docker compose exec backend python manage.py test catalog --keepdb
```

Run one test module:

```bash
docker compose exec backend \
  python manage.py test catalog.tests.test_model_constraints --keepdb
```

Run system checks:

```bash
docker compose exec backend python manage.py check
```

Apply migrations after introducing model changes:

```bash
docker compose exec backend python manage.py migrate
```

Create migrations when needed:

```bash
docker compose exec backend python manage.py makemigrations
```

The application uses **MySQL**, including for evaluating transaction and concurrency behavior. Tests for concurrent stock updates should exercise real, independent database connections rather than relying entirely on mocks.

## Frontend development

The frontend runs via Vite inside its Docker container, with source code mounted from `frontend/`.

Run a production build:

```bash
docker compose exec frontend npm run build
```

## Inventory adjustments and safe retries

Run `docker compose exec backend python manage.py migrate` after pulling changes; setup.sh also applies migrations. In the product editor's inventory tab, choose **Adjust stock**, enter a signed whole-number amount and a reason, then submit. Reservations are checked against current stock under a database row lock; stock and audit history commit together.

API clients use:

```http
POST /api/products/{product_id}/variants/{variant_id}/adjustments/?merchant_id=1
Content-Type: application/json
X-CSRFToken: <current CSRF cookie value>
Idempotency-Key: 6c09fa0c-a406-4f76-9725-0f8e55e1475a
```

```json
{"delta": -3, "reason": "Physical count correction"}
```

Use an authenticated Django session. Generate a new UUID for each intended operation; retain the same key and payload when retrying that operation. New operations return 201; authorized identical replays return 200 with `replayed: true`, original adjustment details and current inventory. Key/payload or operator mismatches return 409. Lock contention returns 503 `inventory_busy` with `Retry-After: 1`; retry manually with the same key. Existing clients may omit the key, but then repeated requests can apply stock repeatedly.

The UI persists retry details in session storage before sending and restores them after a same-tab reload. Busy/uncertain requests offer **Retry same adjustment**; they are never retried automatically. Confirmed success clears the saved retry details. If session storage is unavailable, the UI does not send a mutation. Server keys are retained without automatic expiry; losing browser retry details requires checking activity/current stock before starting another operation.

## Browser tests (Playwright)

Keep the frontend running at `http://127.0.0.1:5173`. Browser tests run on the host and require Node 22.19+ and Chromium. With nvm installed, run `nvm install 22` once if Node 22 is missing. Activate it with `nvm use 22` in every new terminal before running npm/npx commands.

From the repository root:

```bash
cd benchmarks
nvm use 22
npm ci
export PLAYWRIGHT_BROWSERS_PATH=/tmp/merchantops-playwright
npx playwright install chromium
npx playwright test
```

For subsequent runs, activate Node and use the same browser path:

```bash
nvm use 22
PLAYWRIGHT_BROWSERS_PATH=/tmp/merchantops-playwright npx playwright test
```

Run that command from `benchmarks/`. These tests mock API responses and require no login credentials; MySQL concurrency and atomicity checks run separately in the backend suite. See [benchmarks/README.md](benchmarks/README.md) for individual suites and performance measurements. If a command reports `Unexpected token ?`, check `node --version` and run `nvm use 22` again.

## Python formatting

The backend uses **Black 25.1.0** and **isort 6.0.1**, configured in `backend/pyproject.toml`. Development dependencies are listed in `backend/requirements-dev.txt` and are not required for normal application startup.

Install the development dependencies in the running backend container if you want to run formatter commands:

```bash
docker compose exec backend python -m pip install -r requirements-dev.txt
```

Check formatting:

```bash
docker compose exec backend python -m isort --check-only catalog
docker compose exec backend python -m black --check catalog
```

Apply formatting:

```bash
docker compose exec backend python -m isort catalog
docker compose exec backend python -m black catalog
```

Existing Django migration files are excluded from formatter discovery.

## Local configuration and data

The setup script creates `frontend/.env.local` with the merchant ID associated with the seeded Northstar Retail account. This file is local-only and should not be committed.

The development Docker Compose file uses local-only database passwords and binds the exposed services to `127.0.0.1`. Do not reuse this configuration as a production deployment.

The catalogue seeding commands recognize the expected existing dataset and are designed to avoid duplicating sample records when setup is rerun.

## Troubleshooting

Check container status and recent logs:

```bash
docker compose ps
docker compose logs --tail=100 backend
docker compose logs --tail=100 frontend
```

If setup did not finish, rerun:

```bash
./setup.sh
```

An existing demo operator retains its original password. If you forgot your locally chosen password, use appropriate Django user-management commands within the backend container rather than assuming a default password.

## Your assignment

Read **[ASSESSMENT.md](ASSESSMENT.md)** before implementing changes. Include **`ENGINEERING_REPORT.md`** with your completed submission.
