/* Folio: one small browser client, backed entirely by the existing FastAPI service.
 * HTML previews are illustrative. The Preview action opens the actual generated PDF.
 * Results are paginated; PDFs load on demand; ZIP downloads stream through the browser.
 */
"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const drawings = {
  "plus-square":
    '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M12 8v8M8 12h8"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  award: '<circle cx="12" cy="9" r="6"/><path d="m8 14-1 7 5-3 5 3-1-7"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3 2"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 2-2.5 2-2.5 4M12 16h.01"/>',
  code: '<path d="m8 7-5 5 5 5m8-10 5 5-5 5M14 4l-4 16"/>',
  external:
    '<path d="M14 3h7v7m0-7-10 10M10 4H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h13a2 2 0 0 0 2-2v-5"/>',
  settings:
    '<path d="m9 3-1 3-3 1 1 3-2 2 2 2-1 3 3 1 1 3h6l1-3 3-1-1-3 2-2-2-2 1-3-3-1-1-3Z"/><circle cx="12" cy="12" r="3"/>',
  sparkles:
    '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5ZM20 2v4m-2-2h4"/>',
  users:
    '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m20 0v-2a4 4 0 0 0-3-3.87"/><circle cx="9" cy="7" r="4"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  upload:
    '<path d="M12 16V3m-5 5 5-5 5 5M4 16v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/>',
  download: '<path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
  "check-circle": '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  "arrow-right": '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  layers: '<path d="m12 3 10 5-10 5L2 8Zm-9 9 9 5 9-5M3 16l9 5 9-5"/>',
  refresh:
    '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 12-2l2 3M4 16l2 3a7 7 0 0 0 12-2"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
  warning: '<path d="m12 3 10 18H2Z"/><path d="M12 9v5M12 17h.01"/>',
};

function icon(name, extra = "") {
  return `<svg class="${extra}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${drawings[name] || drawings.info}</svg>`;
}

function escapeHTML(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[char],
  );
}

const state = {
  view: "create",
  mode: "manual",
  jobs: [],
  templates: [],
  jobsTotal: 0,
  jobsOffset: 0,
  activeJob: null,
  filter: "",
  resultsOffset: 0,
  results: { items: [], total: 0 },
  layout: "grid",
  busy: false,
  selectionToken: 0,
  resultsToken: 0,
  config: {
    max_recipients: 10000,
    max_body_bytes: 8388608,
    authentication_required: false,
  },
  importText: null,
  imported: [],
  importError: null,
  retrySubmission: null,
  selectedPDF: null,
  pdfToken: 0,
  pdfDocument: null,
  pdfLoadingTask: null,
  pdfRenderTask: null,
};
let toastTimer,
  inputTimer,
  resizeTimer,
  rowNumber = 0;
let pdfLibrary;
let apiKey = "";
try {
  apiKey = sessionStorage.getItem("folio-api-key") || "";
} catch {
  /* Storage is optional. */
}

function toast(message, error = false) {
  clearTimeout(toastTimer);
  $("#toast").textContent = message;
  $("#toast").classList.toggle("error", error);
  $("#toast").hidden = false;
  toastTimer = setTimeout(
    () => {
      $("#toast").hidden = true;
    },
    error ? 8000 : 4500,
  );
}

function errorText(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((item) => {
        const location = (item.loc || [])
          .filter((part) => part !== "body")
          .join(" → ");
        return `${location ? location + ": " : ""}${item.msg || "Invalid value"}`;
      })
      .join("; ");
  return "Something went wrong. Please try again.";
}

async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const headers = {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    };
    if (apiKey) headers["X-API-Key"] = apiKey;
    const response = await fetch(path, {
      ...options,
      headers,
      credentials: "same-origin",
      signal: controller.signal,
    });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(errorText(data.detail));
      error.status = response.status;
      throw error;
    }
    return data;
  } catch (error) {
    if (error.name === "AbortError")
      throw new Error("The request took too long. You can safely retry it.");
    if (error instanceof TypeError)
      throw new Error(
        "Unable to reach the server. Check that the application is running.",
      );
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function showError(error) {
  toast(error.message, true);
  if (error.status === 401 && !$("#settings-dialog").open) openSettings();
}

function localDate() {
  const today = new Date();
  return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
}

function displayDate(value) {
  if (!value) return "";
  const date = new Date(`${value}T12:00:00`);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString(undefined, {
        day: "numeric",
        month: "long",
        year: "numeric",
      });
}

function createdDate(value) {
  return new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function statusBadge(status) {
  const labels = {
    QUEUED: ["Queued", "pending"],
    RUNNING: ["Generating", "running"],
    PROCESSING: ["Generating", "running"],
    COMPLETED: ["Ready", ""],
    COMPLETED_WITH_ERRORS: ["Completed with issues", "attention"],
    FAILED: ["Generation failed", "attention"],
    INVALID: ["Invalid details", "attention"],
  };
  const [label, className] = labels[status] || [status, "pending"];
  return `<span class="status-pill ${className}">${label}</span>`;
}

function certificateInfo() {
  return Object.fromEntries(
    [
      "organization",
      "course",
      "title",
      "issued_on",
      "signatory",
      "signatory_role",
      "template",
    ].map((key) => [key, $(`#${key}`).value.trim()]),
  );
}

async function loadTemplates() {
  const selected = $("#template").value;
  const catalogue = await api("/api/templates");
  state.templates = catalogue.items;
  $("#template").innerHTML = state.templates
    .map(
      (item) =>
        `<option value="${escapeHTML(item.id)}">${escapeHTML(item.name)}</option>`,
    )
    .join("");
  $("#template").value = state.templates.some((item) => item.id === selected)
    ? selected
    : catalogue.default;
  updateForm();
}

function addRecipient(recipient = {}, focus = false) {
  const row = document.createElement("div");
  row.className = "recipient-row";
  const number = ++rowNumber;
  row.innerHTML = `<input data-field="name" maxlength="120" aria-label="Recipient ${number} name" placeholder="Full name" value="${escapeHTML(recipient.name)}"><input data-field="email" aria-label="Recipient ${number} email" placeholder="Email address" value="${escapeHTML(recipient.email)}"><input data-field="reference" maxlength="80" aria-label="Recipient ${number} reference" placeholder="ID or reference" value="${escapeHTML(recipient.reference)}"><button type="button" class="remove-row" aria-label="Remove recipient ${number}" title="Remove recipient">${icon("close")}</button>`;
  $("#recipient-rows").append(row);
  if (focus) row.querySelector("input").focus();
}

function manualRecipients() {
  return $$(".recipient-row")
    .map((row) => {
      const recipient = {};
      row.querySelectorAll("input").forEach((input) => {
        const value = input.value.trim();
        if (value || input.dataset.field === "name")
          recipient[input.dataset.field] = value;
      });
      return recipient;
    })
    .filter((row) => Object.values(row).some(Boolean));
}

// CSV is converted to the same bounded JSON batch. No new upload service is needed.
function parseCSV(text) {
  if (!text.trim()) return [];
  text = text.replace(/^\uFEFF/, "");
  const rows = [];
  let row = [],
    value = "",
    quoted = false,
    closed = false;
  function pushRow() {
    row.push(value.trim());
    if (row.some(Boolean)) rows.push(row);
    if (rows.length > state.config.max_recipients + 1)
      throw new Error(
        `Maximum ${state.config.max_recipients.toLocaleString()} recipients per batch.`,
      );
    row = [];
    value = "";
    closed = false;
  }
  for (let index = 0; index < text.length; index++) {
    const char = text[index];
    if (quoted) {
      if (char === '"') {
        if (text[index + 1] === '"') {
          value += '"';
          index++;
        } else {
          quoted = false;
          closed = true;
        }
      } else value += char;
    } else if (char === ",") {
      row.push(value.trim());
      value = "";
      closed = false;
    } else if (char === "\n" || char === "\r") {
      pushRow();
      if (char === "\r" && text[index + 1] === "\n") index++;
    } else if (char === '"' && !closed && !value.trim()) {
      quoted = true;
      value = "";
    } else if (char === '"' || (closed && char.trim())) {
      throw new Error(
        "Check the CSV quotes. A quoted field must end before the next comma.",
      );
    } else if (!closed) value += char;
  }
  if (quoted)
    throw new Error(
      "The CSV has an unclosed quote. Close the quoted field and try again.",
    );
  pushRow();
  if (!rows.length) return [];
  let headers = ["name", "email", "reference"];
  const first = rows[0].map((cell) => cell.toLowerCase());
  if (
    first.includes("name") ||
    first.includes("email") ||
    first.includes("reference")
  ) {
    if (
      !first.includes("name") ||
      first.some((cell) => !headers.includes(cell)) ||
      new Set(first).size !== first.length
    ) {
      throw new Error(
        "Use a name column, with optional email and reference columns. Remove other or repeated columns.",
      );
    }
    headers = first;
    rows.shift();
  }
  if (rows.length > state.config.max_recipients)
    throw new Error(
      `Maximum ${state.config.max_recipients.toLocaleString()} recipients per batch.`,
    );
  return rows.map((cells, index) => {
    if (cells.length > headers.length)
      throw new Error(
        `Row ${index + 1} has too many columns. Put names containing a comma in quotes.`,
      );
    const recipient = { name: "" };
    headers.forEach((header, position) => {
      if (cells[position] || header === "name")
        recipient[header] = cells[position] || "";
    });
    return recipient;
  });
}

function importedRecipients() {
  const text = $("#recipient-csv").value;
  if (text !== state.importText) {
    state.importText = text;
    try {
      state.imported = parseCSV(text);
      state.importError = null;
    } catch (error) {
      state.imported = [];
      state.importError = error;
    }
  }
  if (state.importError) throw state.importError;
  return state.imported;
}

function recipients() {
  return state.mode === "manual" ? manualRecipients() : importedRecipients();
}

function toCSV(rows) {
  const quote = (value) => `"${String(value || "").replaceAll('"', '""')}"`;
  return (
    "name,email,reference\n" +
    rows
      .map((row) => [row.name, row.email, row.reference].map(quote).join(","))
      .join("\n")
  );
}

function setMode(mode) {
  if (mode === state.mode) return;
  if (mode === "import" && !$("#recipient-csv").value.trim())
    $("#recipient-csv").value = toCSV(manualRecipients());
  if (mode === "manual") {
    let rows = [];
    try {
      rows = importedRecipients();
    } catch {
      /* Leave the existing manual list available. */
    }
    if (rows.length > 100) {
      toast("For more than 100 recipients, keep using Import a list.");
      return;
    }
    if (rows.length) {
      $("#recipient-rows").replaceChildren();
      rows.forEach((row) => addRecipient(row));
    }
  }
  state.mode = mode;
  $$("[data-mode]").forEach((button) => {
    button.classList.toggle("selected", button.dataset.mode === mode);
    button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
  });
  $("#manual-entry").hidden = mode !== "manual";
  $("#import-entry").hidden = mode !== "import";
  updateForm();
}

function updateForm() {
  let rows = [];
  try {
    rows = recipients();
    $("#import-status").textContent = rows.length
      ? `${rows.length.toLocaleString()} recipients found. Ready to generate.`
      : "Use CSV columns: name, email, reference.";
    $("#import-status").style.color = "";
  } catch (error) {
    $("#import-status").textContent = error.message;
    $("#import-status").style.color = "#b18459";
  }
  $("#recipient-count").textContent = rows.length.toLocaleString();
  $("#submit-summary").textContent = rows.length
    ? `${rows.length.toLocaleString()} recipient${rows.length === 1 ? "" : "s"} in this batch`
    : "Ready when you are";
  const missing = rows.filter((row) => !row.name).length;
  $("#recipient-note-text").textContent = missing
    ? `${missing} recipient${missing === 1 ? " is" : "s are"} missing a name. These rows will be marked invalid; other recipients can still succeed.`
    : "Blank rows are skipped. Any invalid recipients will be clearly marked in your results.";
  const info = certificateInfo();
  $("#live-certificate").dataset.template = info.template;
  const template = state.templates.find((item) => item.id === info.template);
  $("#template-name").textContent =
    template?.name || info.template[0].toUpperCase() + info.template.slice(1);
  $("#template-description").textContent =
    template?.description ||
    "One design applies to every recipient in the batch.";
  const preview = {
    org: info.organization || "YOUR ORGANIZATION",
    title: info.title || "Certificate of Completion",
    name: rows.find((row) => row.name)?.name || "Recipient Name",
    course: info.course || "Your course or event",
    date: info.issued_on
      ? `Issued on ${displayDate(info.issued_on)}`
      : "Your issue date",
    signatory: info.signatory || "Signatory Name",
    role: info.signatory_role || "Program Director",
  };
  for (const [key, value] of Object.entries(preview))
    $(`#preview-${key}`).textContent = value;
}

function loadExample() {
  const fields = {
    organization: "Aereo Learning Academy",
    course: "Python Backend Development",
    title: "Certificate of Completion",
    issued_on: localDate(),
    signatory: "Dr. Vidya Pawar",
    signatory_role: "Program Director",
  };
  for (const [key, value] of Object.entries(fields)) $(`#${key}`).value = value;
  state.mode = "manual";
  $("#manual-entry").hidden = false;
  $("#import-entry").hidden = true;
  $$("[data-mode]").forEach((button) => {
    button.classList.toggle("selected", button.dataset.mode === "manual");
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.mode === "manual"),
    );
  });
  $("#recipient-rows").replaceChildren();
  [
    {
      name: "Rithi Aluri",
      email: "rithi@example.com",
      reference: "STUDENT-001",
    },
    {
      name: "Aarav Sharma",
      email: "aarav@example.com",
      reference: "STUDENT-002",
    },
    { name: "Meera Rao", email: "meera@example.com", reference: "STUDENT-003" },
  ].forEach((row) => addRecipient(row));
  $("#recipient-csv").value = "";
  $("#form-error").hidden = true;
  updateForm();
  toast("Example loaded. Make it yours, or generate this sample batch.");
}

function showView(view) {
  state.view = view;
  for (const name of ["create", "library", "history"])
    $(`#${name}-view`).hidden = name !== view;
  $$(".nav-item[data-view]").forEach((button) =>
    button.classList.toggle("active", button.dataset.view === view),
  );
  $("#breadcrumb-current").textContent = {
    create: "Create certificates",
    library: "Generated certificates",
    history: "Batch history",
  }[view];
  window.scrollTo({ top: 0, behavior: "instant" });
  if (view === "library" && state.activeJob) loadResults().catch(showError);
  if (view === "history") loadJobs().catch(showError);
}

function renderJobs() {
  $("#sidebar-jobs").innerHTML = state.jobs.length
    ? state.jobs
        .slice(0, 3)
        .map(
          (job) =>
            `<button class="sidebar-job" data-job="${job.id}"><span class="job-dot"></span><span><strong>${escapeHTML(job.certificate.course)}</strong><small>${job.total.toLocaleString()} recipients · ${createdDate(job.created_at)}</small></span></button>`,
        )
        .join("")
    : '<p class="muted small">Your batches will appear here.</p>';
  $("#history-list").innerHTML = state.jobs.length
    ? state.jobs
        .map(
          (job) =>
            `<article class="history-card"><span class="history-icon">${icon("layers")}</span><div class="history-info"><h3>${escapeHTML(job.certificate.course)}</h3><p>${escapeHTML(job.certificate.organization)} · ${createdDate(job.created_at)} · ${job.total.toLocaleString()} recipients</p></div><span class="history-count">${job.succeeded.toLocaleString()} ready</span>${statusBadge(job.status)}<button class="text-button" data-job="${job.id}">View batch ${icon("arrow-right")}</button></article>`,
        )
        .join("")
    : '<div class="empty-state"><h2>No batches yet.</h2><p>Your certificate batches will appear here after you generate them.</p><button class="button primary" data-view="create">Create your first batch</button></div>';
  $("#history-page-label").textContent = state.jobsTotal
    ? `Showing ${state.jobsOffset + 1}–${state.jobsOffset + state.jobs.length} of ${state.jobsTotal} batches`
    : "0 batches";
  $("#previous-jobs").disabled = state.jobsOffset === 0;
  $("#next-jobs").disabled = state.jobsOffset + 25 >= state.jobsTotal;
  const jobs = [...state.jobs];
  if (state.activeJob && !jobs.some((job) => job.id === state.activeJob.id))
    jobs.unshift(state.activeJob);
  $("#batch-select").innerHTML = jobs
    .map(
      (job) =>
        `<option value="${job.id}">${escapeHTML(job.certificate.course)} · ${createdDate(job.created_at)} · ${job.total} recipients</option>`,
    )
    .join("");
  if (state.activeJob) $("#batch-select").value = state.activeJob.id;
  $("#no-jobs").hidden = !!state.activeJob || state.jobs.length > 0;
  $("#job-results").hidden = !state.activeJob;
  renderLatest();
}

function renderLatest() {
  const job = state.activeJob || state.jobs[0];
  $("#latest-batch-card").hidden = !job;
  if (!job) return;
  $("#latest-batch-card").innerHTML =
    `<div class="latest-label">${state.activeJob ? "YOUR SELECTED BATCH" : "LATEST BATCH"}${statusBadge(job.status)}</div><h3>${escapeHTML(job.certificate.course)}</h3><p>${job.succeeded.toLocaleString()} ready · ${job.pending.toLocaleString()} in progress${job.failed ? ` · ${job.failed} need attention` : ""}</p><button class="text-button" data-job="${job.id}">View certificates ${icon("arrow-right")}</button>`;
  $("#nav-count").textContent = job.succeeded.toLocaleString();
  $("#nav-count").title = "Ready certificates in your selected batch";
}

async function loadJobs() {
  const page = await api(`/api/jobs?limit=25&offset=${state.jobsOffset}`);
  state.jobs = page.items;
  state.jobsTotal = page.total;
  renderJobs();
  return page;
}

function renderJob() {
  const job = state.activeJob;
  if (!job) return;
  $("#job-results").hidden = false;
  $("#no-jobs").hidden = true;
  $("#job-org").textContent = job.certificate.organization;
  $("#job-course").textContent = job.certificate.course;
  $("#job-meta").textContent =
    `Created ${createdDate(job.created_at)} · Issued ${displayDate(job.certificate.issued_on)} · ${state.templates.find((item) => item.id === job.certificate.template)?.name || "Classic"} design`;
  $("#job-status").outerHTML = statusBadge(job.status).replace(
    "<span ",
    '<span id="job-status" ',
  );
  for (const [key, value] of Object.entries({
    total: job.total,
    success: job.succeeded,
    failed: job.failed,
    pending: job.pending,
  }))
    $(`#stat-${key}`).textContent = value.toLocaleString();
  $("#progress-percent").textContent = `${job.progress_percent}%`;
  $("#progress-fill").style.width = `${job.progress_percent}%`;
  $("#job-progress").setAttribute("aria-valuenow", job.progress_percent);
  $("#progress-label").textContent = job.pending
    ? `${job.succeeded + job.failed} of ${job.total} recipients processed`
    : "Every recipient has been processed";
  $("#job-hint").textContent = job.pending
    ? job.status === "QUEUED"
      ? "Your batch is queued. Generation starts when the worker is available."
      : "Generating your certificates. This page updates automatically."
    : job.failed
      ? `${job.failed} recipient${job.failed === 1 ? " needs" : "s need"} attention. View the details below; successful PDFs are ready.`
      : "All certificates are ready. Preview a PDF or download the complete batch.";
  $("#download-zip").disabled = job.pending > 0 || job.succeeded === 0;
  state.jobs = state.jobs.map((existing) =>
    existing.id === job.id ? job : existing,
  );
  renderLatest();
}

async function selectJob(id, navigate = true) {
  const token = ++state.selectionToken;
  const job = await api(`/api/jobs/${id}`);
  if (token !== state.selectionToken) return;
  state.activeJob = job;
  state.filter = "";
  state.resultsOffset = 0;
  $$("[data-filter]").forEach((button) =>
    button.classList.toggle("active", !button.dataset.filter),
  );
  renderJobs();
  renderJob();
  if (navigate) showView("library");
  else await loadResults();
}

function miniCertificate(info, recipient) {
  return `<div class="certificate-sheet" data-template="${escapeHTML(info.template || "classic")}"><div class="certificate-inner"><span class="certificate-org">${escapeHTML(info.organization)}</span><span class="certificate-flourish"></span><h3>${escapeHTML(info.title)}</h3><span class="certificate-presented">THIS CERTIFICATE IS PROUDLY PRESENTED TO</span><strong class="certificate-name">${escapeHTML(recipient.name)}</strong><span class="certificate-for">for successfully completing</span><strong class="certificate-course">${escapeHTML(info.course)}</strong><span class="certificate-date">Issued on ${displayDate(info.issued_on)}</span><strong class="certificate-signatory">${escapeHTML(info.signatory)}</strong><span class="certificate-role">${escapeHTML(info.signatory_role)}</span><span class="certificate-footer">Certificate ID: ${recipient.id}</span></div></div>`;
}

function renderResults() {
  const container = $("#certificate-results");
  container.classList.toggle("list-layout", state.layout === "list");
  const job = state.activeJob;
  if (!job) return;
  const rows = state.results.items;
  container.innerHTML = rows.length
    ? rows
        .map((row) => {
          const ready = row.status === "COMPLETED";
          const pending = ["QUEUED", "PROCESSING"].includes(row.status);
          const visual = ready
            ? `<div class="mini-certificate" data-preview="${row.id}" role="button" tabindex="0" aria-label="Preview ${escapeHTML(row.name)} certificate">${miniCertificate(job.certificate, row)}</div>`
            : `<div class="unavailable-certificate ${pending ? "pending" : ""}">${icon(pending ? "refresh" : "warning", pending ? "spin" : "")}<span>${pending ? "Your certificate is on its way" : "This recipient needs attention"}</span></div>`;
          return `<article class="certificate-card">${visual}<div class="card-body"><div class="card-title"><h3 title="${escapeHTML(row.name)}">${escapeHTML(row.name || `Recipient ${row.index + 1}`)}</h3>${statusBadge(row.status)}</div><div class="card-meta">${escapeHTML(row.email || row.reference || `Recipient #${row.index + 1}`)}</div>${row.error ? `<p class="card-error">${escapeHTML(row.error)}</p>` : ""}<div class="card-actions"><button class="button secondary" data-preview="${row.id}" ${ready ? "" : "disabled"}>${icon("eye")}Preview</button><button class="button secondary" data-download="${row.id}" ${ready ? "" : "disabled"}>${icon("download")}PDF</button></div></div></article>`;
        })
        .join("")
    : `<div class="filter-empty">${state.filter === "attention" ? "No recipients need attention. Looking good!" : state.filter === "COMPLETED" ? "No certificates are ready yet. They will appear as generation finishes." : "There are no recipients on this page."}</div>`;
  $("#result-page-label").textContent = state.results.total
    ? `Showing ${state.resultsOffset + 1}–${state.resultsOffset + rows.length} of ${state.results.total.toLocaleString()} recipients`
    : "0 matching recipients";
  $("#previous-results").disabled = state.resultsOffset === 0;
  $("#next-results").disabled = state.resultsOffset + 12 >= state.results.total;
}

async function loadResults() {
  if (!state.activeJob) return;
  const token = ++state.resultsToken;
  const jobId = state.activeJob.id;
  const filter =
    state.filter === "attention"
      ? "&attention=true"
      : state.filter
        ? `&status=${state.filter}`
        : "";
  $("#results-loading").hidden = false;
  try {
    const page = await api(
      `/api/jobs/${jobId}/certificates?limit=12&offset=${state.resultsOffset}${filter}`,
    );
    if (token !== state.resultsToken || state.activeJob.id !== jobId) return;
    state.results = page;
    renderResults();
  } finally {
    if (token === state.resultsToken) $("#results-loading").hidden = true;
  }
}

async function generate(event) {
  event.preventDefault();
  if (state.busy) return;
  $("#form-error").hidden = true;
  if (!$("#certificate-form").reportValidity()) return;
  try {
    const list = recipients();
    if (!list.length)
      throw new Error(
        "Add at least one recipient name, or import a list, to get started.",
      );
    if (list.length > state.config.max_recipients)
      throw new Error(
        `A batch can contain up to ${state.config.max_recipients.toLocaleString()} recipients.`,
      );
    const body = JSON.stringify({
      certificate: certificateInfo(),
      recipients: list,
    });
    if (new Blob([body]).size > state.config.max_body_bytes)
      throw new Error(
        "This batch is too large. Split your recipients into smaller lists and try again.",
      );
    if (state.retrySubmission?.body !== body)
      state.retrySubmission = { body, key: crypto.randomUUID() };
    state.busy = true;
    $("#generate-button").disabled = true;
    $("#generate-label").textContent = "Creating your batch…";
    const job = await api("/api/jobs", {
      method: "POST",
      body,
      headers: { "Idempotency-Key": state.retrySubmission.key },
    });
    state.retrySubmission = null;
    state.jobsOffset = 0;
    // Keep the accepted ID even if a subsequent history refresh fails.
    state.activeJob = job;
    state.resultsOffset = 0;
    state.filter = "";
    $$("[data-filter]").forEach((button) =>
      button.classList.toggle("active", !button.dataset.filter),
    );
    renderJob();
    renderJobs();
    showView("library");
    toast(
      job.pending
        ? "Batch created. Your certificates are on their way."
        : "Batch processed. Check the recipient results.",
    );
    await loadJobs().catch(showError);
  } catch (error) {
    $("#form-error").textContent = error.message;
    $("#form-error").hidden = false;
    showError(error);
  } finally {
    state.busy = false;
    $("#generate-button").disabled = false;
    $("#generate-label").textContent = "Generate certificates";
  }
}

function nativeDownload(url) {
  // The native browser download streams to disk, instead of loading a potentially large ZIP into JS.
  const link = document.createElement("a");
  link.href = url;
  link.download = "";
  document.body.append(link);
  link.click();
  link.remove();
}

async function previewCertificate(id) {
  const row = state.results.items.find((item) => item.id === id);
  if (!row || row.status !== "COMPLETED") return;
  const token = ++state.pdfToken;
  state.selectedPDF = row;
  $("#pdf-name").textContent = row.name || "Certificate preview";
  $("#pdf-canvas").hidden = true;
  $("#pdf-loading").hidden = false;
  $("#pdf-loading").textContent = "Opening your certificate…";
  if (!$("#pdf-dialog").open) $("#pdf-dialog").showModal();
  try {
    if (!pdfLibrary) pdfLibrary = import("/static/vendor/pdf.mjs");
    const pdfjs = await pdfLibrary;
    if (token !== state.pdfToken || !$("#pdf-dialog").open) return;
    pdfjs.GlobalWorkerOptions.workerSrc = "/static/vendor/pdf.worker.mjs";
    const loadingTask = pdfjs.getDocument({
      url: `/api/certificates/${id}/preview`,
      withCredentials: true,
      httpHeaders: apiKey ? { "X-API-Key": apiKey } : {},
      // Certificates embed their own fonts; no external font or image asset requests are needed.
      isEvalSupported: false,
    });
    state.pdfLoadingTask = loadingTask;
    const pdf = await loadingTask.promise;
    if (token !== state.pdfToken || !$("#pdf-dialog").open) {
      await loadingTask.destroy();
      return;
    }
    state.pdfDocument = pdf;
    await drawPDF(pdf, token);
  } catch (error) {
    if (token === state.pdfToken)
      $("#pdf-loading").textContent =
        "Unable to preview this PDF. Try downloading it, or check your connection settings.";
  }
}

async function drawPDF(pdf, token) {
  state.pdfRenderTask?.cancel();
  const page = await pdf.getPage(1);
  if (token !== state.pdfToken) return;
  const natural = page.getViewport({ scale: 1 });
  const available = Math.max(120, $(".pdf-content").clientWidth - 48);
  const availableHeight = Math.max(100, $(".pdf-content").clientHeight - 48);
  const viewport = page.getViewport({
    scale: Math.min(
      available / natural.width,
      availableHeight / natural.height,
    ),
  });
  const density = Math.min(window.devicePixelRatio || 1, 2);
  const canvas = $("#pdf-canvas");
  canvas.width = Math.ceil(viewport.width * density);
  canvas.height = Math.ceil(viewport.height * density);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;
  state.pdfRenderTask = page.render({
    canvasContext: canvas.getContext("2d"),
    viewport,
    transform: density === 1 ? null : [density, 0, 0, density, 0, 0],
  });
  try {
    await state.pdfRenderTask.promise;
  } catch (error) {
    if (error.name === "RenderingCancelledException") return;
    throw error;
  }
  if (token === state.pdfToken) {
    canvas.hidden = false;
    $("#pdf-loading").hidden = true;
  }
}

function openSettings() {
  $("#api-key").value = apiKey;
  if (!$("#settings-dialog").open) $("#settings-dialog").showModal();
}

async function saveSettings(event) {
  event.preventDefault();
  const previousKey = apiKey;
  apiKey = $("#api-key").value.trim();
  try {
    if (apiKey || !state.config.authentication_required)
      await api("/ui-session", { method: "POST" });
    else await api("/ui-session", { method: "DELETE" });
    await loadTemplates();
    await loadJobs();
    try {
      if (apiKey) sessionStorage.setItem("folio-api-key", apiKey);
      else sessionStorage.removeItem("folio-api-key");
    } catch {
      /* The current tab can still use the key without storage. */
    }
    $("#settings-dialog").close();
    if (state.activeJob) await selectJob(state.activeJob.id, false);
    else if (state.jobs.length) await selectJob(state.jobs[0].id, false);
    toast("Workspace connected.");
  } catch (error) {
    apiKey = previousKey;
    showError(error);
  }
}

async function checkHealth() {
  try {
    await api("/health");
    document.body.classList.remove("offline");
    document.body.classList.add("online");
    $("#connection-label").textContent = "Connected";
    $("#sidebar-connection").textContent = "Connected";
  } catch {
    document.body.classList.remove("online");
    document.body.classList.add("offline");
    $("#connection-label").textContent = "Offline";
    $("#sidebar-connection").textContent = "Server offline";
  }
}

let pollCount = 0;
async function poll() {
  try {
    if (document.visibilityState !== "hidden") {
      if (++pollCount % 8 === 0) await checkHealth();
      const job = state.activeJob;
      if (job?.pending > 0) {
        const updated = await api(`/api/jobs/${job.id}`);
        if (state.activeJob?.id === updated.id) {
          state.activeJob = updated;
          renderJob();
          if (state.view === "library") await loadResults();
          if (!updated.pending) {
            await loadJobs();
            toast(
              updated.failed
                ? "Batch finished. Check the recipients that need attention."
                : "All your certificates are ready!",
            );
          }
        }
      }
    }
  } catch (error) {
    // Do not spam notifications for a temporarily unreachable server. Refresh allows an explicit retry.
    if (error.status === 401) {
      await checkHealth();
    }
  } finally {
    setTimeout(poll, 2000);
  }
}

async function importFile(file) {
  if (!file) return;
  try {
    if (file.size > state.config.max_body_bytes)
      throw new Error("This CSV is too large. Split it into smaller files.");
    $("#recipient-csv").value = await file.text();
    updateForm();
    if (state.importError) throw state.importError;
    toast(
      `${state.imported.length.toLocaleString()} recipients loaded from ${file.name}.`,
    );
  } catch (error) {
    showError(error);
  } finally {
    $("#csv-file").value = "";
  }
}

document.addEventListener("click", async (event) => {
  const target = event.target.closest("button, [data-preview], [data-close]");
  if (!target || target.disabled) return;
  try {
    if (target.dataset.view) showView(target.dataset.view);
    else if (target.dataset.mode) setMode(target.dataset.mode);
    else if (target.dataset.job) await selectJob(target.dataset.job);
    else if (target.dataset.preview)
      await previewCertificate(target.dataset.preview);
    else if (target.dataset.download)
      nativeDownload(`/api/certificates/${target.dataset.download}/download`);
    else if (target.dataset.close) $(`#${target.dataset.close}`).close();
    else if (target.dataset.filter !== undefined) {
      state.filter = target.dataset.filter;
      state.resultsOffset = 0;
      $$("[data-filter]").forEach((button) =>
        button.classList.toggle("active", button === target),
      );
      await loadResults();
    } else if (target.classList.contains("remove-row")) {
      target.closest(".recipient-row").remove();
      updateForm();
    }
  } catch (error) {
    showError(error);
  }
});

$("#certificate-results").addEventListener("keydown", (event) => {
  if (
    ["Enter", " "].includes(event.key) &&
    event.target.matches(".mini-certificate")
  ) {
    event.preventDefault();
    previewCertificate(event.target.dataset.preview);
  }
});
$("#certificate-form").addEventListener("submit", generate);
$("#certificate-form").addEventListener("input", (event) => {
  event.target.classList.add("touched");
  clearTimeout(inputTimer);
  inputTimer = setTimeout(updateForm, 100);
  $("#form-error").hidden = true;
});
$("#example-button").addEventListener("click", loadExample);
$("#add-recipient").addEventListener("click", () => {
  if ($$(".recipient-row").length >= 100) {
    toast("For larger lists, use Import a list.");
    return;
  }
  addRecipient({}, true);
  updateForm();
});
$("#clear-recipients").addEventListener("click", () => {
  $("#recipient-rows").replaceChildren();
  addRecipient();
  addRecipient();
  $("#recipient-csv").value = "";
  updateForm();
});
$("#csv-example").addEventListener("click", () => {
  $("#recipient-csv").value =
    "name,email,reference\nRithi Aluri,rithi@example.com,STUDENT-001\nAarav Sharma,aarav@example.com,STUDENT-002\nMeera Rao,meera@example.com,STUDENT-003";
  updateForm();
});
$("#csv-file").addEventListener("change", (event) =>
  importFile(event.target.files[0]),
);
const zone = $(".upload-zone");
for (const type of ["dragenter", "dragover"])
  zone.addEventListener(type, (event) => {
    event.preventDefault();
    zone.classList.add("drag-over");
  });
for (const type of ["dragleave", "drop"])
  zone.addEventListener(type, (event) => {
    event.preventDefault();
    zone.classList.remove("drag-over");
  });
zone.addEventListener("drop", (event) =>
  importFile(event.dataTransfer.files[0]),
);
$("#batch-select").addEventListener("change", (event) =>
  selectJob(event.target.value).catch(showError),
);
$("#refresh-button").addEventListener("click", async () => {
  try {
    await loadJobs();
    if (state.activeJob) await selectJob(state.activeJob.id);
    else if (state.jobs.length) await selectJob(state.jobs[0].id);
    toast("Results refreshed.");
  } catch (error) {
    showError(error);
  }
});
for (const [id, direction] of [
  ["previous-results", -1],
  ["next-results", 1],
])
  $(`#${id}`).addEventListener("click", () => {
    state.resultsOffset = Math.max(0, state.resultsOffset + direction * 12);
    loadResults().catch(showError);
  });
for (const [id, direction] of [
  ["previous-jobs", -1],
  ["next-jobs", 1],
])
  $(`#${id}`).addEventListener("click", () => {
    state.jobsOffset = Math.max(0, state.jobsOffset + direction * 25);
    loadJobs().catch(showError);
  });
for (const layout of ["grid", "list"])
  $(`#${layout}-view-button`).addEventListener("click", () => {
    state.layout = layout;
    $("#grid-view-button").classList.toggle("active", layout === "grid");
    $("#list-view-button").classList.toggle("active", layout === "list");
    renderResults();
  });
$("#download-zip").addEventListener("click", () => {
  if (
    state.activeJob &&
    !state.activeJob.pending &&
    state.activeJob.succeeded
  ) {
    nativeDownload(`/api/jobs/${state.activeJob.id}/download`);
    toast(
      "Your ZIP download is starting. Large batches may take a moment to package.",
    );
  }
});
$("#modal-download").addEventListener("click", () => {
  if (state.selectedPDF)
    nativeDownload(`/api/certificates/${state.selectedPDF.id}/download`);
});
$("#pdf-dialog").addEventListener("close", () => {
  state.pdfToken++;
  state.pdfRenderTask?.cancel();
  // PDF.js 6 owns destruction on the loading task, not PDFDocumentProxy.
  state.pdfLoadingTask?.destroy().catch(() => {});
  state.pdfLoadingTask = null;
  state.pdfRenderTask = null;
  state.pdfDocument = null;
  state.selectedPDF = null;
  $("#pdf-canvas").width = 0;
  $("#pdf-canvas").height = 0;
});
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (state.pdfDocument && $("#pdf-dialog").open)
      drawPDF(state.pdfDocument, state.pdfToken).catch(showError);
  }, 200);
});
$("#settings-button").addEventListener("click", openSettings);
$("#settings-form").addEventListener("submit", saveSettings);
$("#help-button").addEventListener("click", () =>
  $("#help-dialog").showModal(),
);
$$("dialog").forEach((dialog) =>
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) {
      const box = dialog.getBoundingClientRect();
      if (
        event.clientX < box.left ||
        event.clientX > box.right ||
        event.clientY < box.top ||
        event.clientY > box.bottom
      )
        dialog.close();
    }
  }),
);

async function initialize() {
  $$("[data-icon]").forEach((element) => {
    element.innerHTML = icon(element.dataset.icon);
  });
  $("#issued_on").value = localDate();
  addRecipient();
  addRecipient();
  updateForm();
  try {
    state.config = await api("/ui-config");
    $("#import-limit").textContent =
      `up to ${state.config.max_recipients.toLocaleString()} recipients`;
    if (apiKey) await api("/ui-session", { method: "POST" });
    await loadTemplates();
    await checkHealth();
    await loadJobs();
    if (state.jobs.length) await selectJob(state.jobs[0].id, false);
  } catch (error) {
    showError(error);
  }
  poll();
}
initialize();
