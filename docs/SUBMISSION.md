# Folio — project submission

- **Working application:** https://aereo-assignment-certificate-genera.vercel.app/
- **GitHub source:** https://github.com/rithinreddy0/Aereo-Assignment-Certificate-Generator
- **Interactive API documentation:** https://aereo-assignment-certificate-genera.vercel.app/docs
- **Backend:** https://folio-aereo-api.onrender.com
- **Backend health:** https://folio-aereo-api.onrender.com/health

Frontend: Vercel Hobby. Backend: Render Free, in the Folio Assignment workspace.
Database: Neon Free PostgreSQL. The database dashboard and connection credentials
are private; reviewers use the application and API links above.

## Reviewer walkthrough

1. Open the application and click **Try an example**.
2. Click **Generate certificates** and wait for all three recipients to finish.
3. Preview a generated PDF, download an individual PDF, and download the batch ZIP.
4. Open **Batch history** to revisit completed jobs.
5. Open `/docs` to inspect and try the API.

The demo requires no API key. It uses the same API and worker as the local app.
Jobs and PDFs persist in PostgreSQL, including after backend restarts. Only
temporary PDF/ZIP caches are stored on Render's ephemeral filesystem.

Render's free service sleeps when idle. The first visit may take about a minute
to wake the backend. Free provider usage limits apply. Use example recipient
data for this public demo; visitors share its batch history.

## Verification

Verified on October 9, 2026: frontend connection, three-recipient generation,
actual PDF preview, individual PDF, ZIP containing three PDFs, OpenAPI, and
interactive documentation. GitHub CI also checks the PostgreSQL worker and
PDF restoration after deleting the local cache.

Local suite: 51 passed, with the PostgreSQL-only test skipped locally. GitHub CI
runs that test against PostgreSQL 18 as well as the suite on Python 3.11/3.12.
