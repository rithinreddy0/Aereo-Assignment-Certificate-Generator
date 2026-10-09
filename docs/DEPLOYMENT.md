# Free deployment: Vercel + Render + Neon

The frontend is static HTML/CSS/JavaScript served by Vercel. Render runs FastAPI and
an embedded PDF worker in one free web service. Neon PostgreSQL stores jobs,
recipient outcomes, and generated PDF bytes. SQLite remains the default locally.

## 1. Neon database

Create a Free project and copy its PostgreSQL connection URL from **Connect**.
Keep `sslmode=require` enabled. Pooler URLs are supported. Do not commit this URL.
No SQL setup is needed: the backend creates its tables on startup.

PDFs are small database blobs for this assignment. Local files and ZIP archives
are caches: after a restart, PDFs restore from PostgreSQL automatically. Existing
local SQLite jobs are not copied into the cloud database.

## 2. Render backend

Connect this repository using **New → Blueprint** and `render.yaml`, or create a
Python web service using these settings:

- Plan: **Free**, Python 3.12.
- Build: `pip install -c requirements.lock .`
- Start: `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers`
- Health check: `/health`.
- `DATABASE_URL`: the secret Neon connection URL.
- `CERT_EMBEDDED_WORKER`: `true`.
- `CERT_DATA_DIR`: `/tmp/folio`.
- `CERT_MAX_RECIPIENTS`: `500` for the free demo.
- `CERT_POLL_SECONDS`: `5`.
- Optional `CERT_API_KEY`: choose a secret for a restricted demo. Reviewers enter it
  in **Connection settings**; never place it in GitHub or a public frontend variable.

Use one Uvicorn worker. A PostgreSQL transaction advisory lock coordinates PDF
generation across overlapping deployments. The worker resumes interrupted jobs.
Do not create a separate Render worker service; free compute is for web services.

Render Free sleeps after inactivity. Queued work resumes on the next visit. Free
hosting is suitable for a submission/demo, not an always-running production queue.
The frontend allows 120 seconds for a cold start. Resource allowances apply.

## 3. Vercel frontend

Import the same repository, with repository root as the root directory and
framework **Other**. The checked-in `vercel.json` supplies the build command.
Remove any old dashboard override that sets an output directory or Python framework.

Set `BACKEND_URL` to the deployed Render HTTPS origin, without a path:
`https://YOUR-SERVICE.onrender.com`. Redeploy after changing it.

`npm run build` creates `.vercel/output` using Vercel's Build Output API. Only
static frontend assets are published. API requests, UI configuration, session
cookies, OpenAPI, PDF previews, and downloads proxy through the Vercel origin.
This preserves native downloads and SameSite cookies without cross-origin CORS.

## 4. Check before submission

Open the Vercel URL, choose **Try an example**, generate certificates, wait for
completion, preview a PDF, download it, and download the ZIP. Check **Batch
history** and `/docs`. Redeploy the backend and verify that the previous PDF
still downloads. The GitHub workflow tests PostgreSQL persistence and cache loss.

Submit the Vercel URL and GitHub repository URL. The Neon dashboard is private;
it is not a public submission link. Keep credentials outside the repository.

## Provider references

- [Vercel Hobby](https://vercel.com/docs/plans/hobby)
- [Vercel Build Output API](https://vercel.com/docs/build-output-api)
- [Render free services and sleep/storage limits](https://render.com/docs/free)
- [Neon free PostgreSQL plan](https://neon.com/pricing)

Render's free PostgreSQL expires after 30 days; use Neon for this deployment.
An unrestricted demo shares its history with visitors. Use synthetic example
names, or enable `CERT_API_KEY` before storing private recipient information.
