# VexNet Hub Deployment Guide

## Infrastructure

| Resource | Value |
|---|---|
| Platform | Azure App Service (Linux) |
| Resource Group | `vexnet-rg` |
| App Service | `vexnet-hub` |
| App Service Plan | `vexnet-plan` (B1 / Basic) |
| Runtime | Node.js 20 LTS |
| Region | East US |
| URL | https://vexnet-hub.azurewebsites.net |
| Database | Azure SQL Server (`vexnet-db-srv.database.windows.net`, database `vexnet`) |

## App Settings

These environment variables must be configured on the App Service:

| Setting | Purpose |
|---|---|
| `AZURE_SQL_SERVER` | SQL Server hostname |
| `AZURE_SQL_DATABASE` | Database name |
| `AZURE_SQL_USER` | Database username |
| `AZURE_SQL_PASSWORD` | Database password |
| `JWT_SECRET` | Secret for JWT token signing |
| `VEXNET_SERVER_NAME` | Display name for the server |
| `PORT` | Must be `8080` (Azure default) |
| `WEBSITE_RUN_FROM_PACKAGE` | Must be `1` (mounts zip as read-only filesystem) |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | Must be `false` (build is done locally) |
| `WEBSITE_NODE_DEFAULT_VERSION` | `20` |

The app constructs its database connection from the `AZURE_SQL_*` variables (see `src/lib/db.ts`). You can alternatively set `DATABASE_URL` directly.

## Build

The app uses Next.js standalone output mode (`next.config.js` sets `output: 'standalone'`). The build produces a self-contained server at `.next/standalone/` with only the required `node_modules`.

```bash
cd vex-chat
npm run build
```

This creates `.next/standalone/` containing `server.js`, `node_modules/`, and `.next/server/`.

## Deploy

### 1. Build the project

```bash
cd vex-chat
npm run build
```

### 2. Copy static assets into standalone

Next.js standalone output does not include static files by default. Copy them in:

```bash
cp -r .next/static .next/standalone/.next/static
```

If a `public/` directory exists:
```bash
cp -r public .next/standalone/public
```

### 3. Create the deployment zip

The zip must contain the standalone output **nested under `.next/standalone/`**, not at the root. The startup command expects this path.

Use Python to create the zip (ensures forward-slash paths on Windows):

```bash
python -c "
import zipfile, os
src = '.next/standalone'
dst = 'deploy.zip'
with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(src):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, src).replace(os.sep, '/')
            zf.write(full, '.next/standalone/' + rel)
print(f'Created {dst} with {len(zf.namelist())} files')
"
```

**Important:** Do not use PowerShell's `Compress-Archive` — it can produce zips with backslash paths that fail on Linux.

### 4. Deploy to Azure

```bash
az webapp deploy \
  --resource-group vexnet-rg \
  --name vexnet-hub \
  --src-path deploy.zip \
  --type zip
```

The CLI polls until the site starts. It may report a timeout even if the site starts successfully — check the site URL directly if this happens.

**Tip:** If Kudu returns 502 errors from repeated deployments, stop the app first:
```bash
az webapp stop --resource-group vexnet-rg --name vexnet-hub
# wait ~30 seconds
az webapp start --resource-group vexnet-rg --name vexnet-hub
# then deploy
az webapp deploy --resource-group vexnet-rg --name vexnet-hub --src-path deploy.zip --type zip
```

### 5. Verify

```bash
curl -s https://vexnet-hub.azurewebsites.net/api/constitution | python -m json.tool
```

## Startup Command

The App Service startup command is:

```
node .next/standalone/server.js
```

This is configured via:
```bash
az webapp config set --resource-group vexnet-rg --name vexnet-hub \
  --startup-file "node .next/standalone/server.js"
```

The standalone `server.js` reads the `PORT` environment variable (defaults to 3000, Azure sets it to 8080).

## Zip Structure

The deployment zip must have this structure:

```
deploy.zip
└── .next/
    └── standalone/
        ├── server.js              # Entry point
        ├── package.json
        ├── node_modules/          # Minimal dependencies (next, react, prisma, etc.)
        │   ├── next/
        │   ├── react/
        │   ├── @prisma/
        │   └── ...
        ├── prisma/
        │   └── schema.prisma
        └── .next/
            ├── server/            # Compiled server pages/routes
            └── static/            # Static assets (copied in step 2)
```

On the App Service, this mounts at `/home/site/wwwroot/.next/standalone/...`.

## Troubleshooting

### Check runtime logs
```bash
az webapp log tail --resource-group vexnet-rg --name vexnet-hub
```

### Download all logs
```bash
az webapp log download --resource-group vexnet-rg --name vexnet-hub --log-file logs.zip
```

The Docker container logs are in `LogFiles/<date>_<instance>_default_docker.log`.

### Common errors

| Error | Cause | Fix |
|---|---|---|
| `Cannot find module 'next'` | Zip has wrong structure (files at root instead of under `.next/standalone/`) | Rebuild zip with correct nesting (see step 3) |
| `Cannot find module 'next'` | Zip created with backslash paths on Windows | Use Python `zipfile` instead of PowerShell `Compress-Archive` |
| Prisma `ETIMEOUT` connecting to SQL Server | Azure SQL firewall not allowing App Service IP, or cold start latency | Check Azure SQL firewall rules; these often resolve after first request |
| Site fails to start within 10 minutes | App crashes on startup repeatedly | Check docker logs for the actual error |
| Kudu 502 during deployment | Too many rapid deployment attempts | Stop and restart the app, then retry |

### API routes and force-dynamic

All API routes use `export const dynamic = 'force-dynamic'` to prevent Next.js from attempting to prerender them at build time. This is required because the routes access the database, which isn't available during the build step.

## Database Migrations

Prisma migrations are at `prisma/migrations/`. The app checks for existing tables on startup and runs migrations if needed (see the `[migrate]` log entries in docker logs).
