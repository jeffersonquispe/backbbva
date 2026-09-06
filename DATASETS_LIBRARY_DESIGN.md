# Datasets Library — design document

Status: **draft for review** — nothing in this document has been implemented.
Owner: carlosdavid.rojas · Drafted with Claude Sonnet 5, 2026-09-06.

## 1. Problem statement

Dataset management today is duplicated across two frontend flows that each
grew their own slice of CRUD:

- **Modelos** (`ModelFormModal.tsx`): a `<select>` of dataset names + the
  already-computed field summary, used to pick a training dataset and its
  fields. No upload, no delete.
- **Testing** (`NewTestRunModal.tsx` + `DatasetDetailModal.tsx`): upload
  button, dataset picker, a detail modal with field distributions and a
  delete action.

Both call the same backend (`GET/POST /datasets`, `GET /datasets/{name}
/summary`, `DELETE /datasets/{name}`) and the same TanStack Query key
(`["datasets"]`), so the duplication today is UI-only, not data-model-only —
which is good news, it means centralizing is mostly a UI consolidation, not
a migration.

There's also a third, currently-inert spot: `alerta.$id.tsx` has an "Al
dataset" button in an analyst's action bar that opens a justification modal
and does **nothing** on submit (no API call, no target-dataset picker). This
is a stubbed fourth ingestion path the user wants wired up.

Goal: make **Biblioteca → Datasets** the single place to list, upload,
delete, inspect, and derive datasets. Modelos/Testing keep *picking* a
dataset for their own purpose, but stop *managing* datasets.

## 2. Current state (verified in code)

### Backend (`aria-api`)

**Domain shape today** — `application/ports/dataset_port.py`:
```
DatasetRecord(name: str, row_count: int)
DatasetRepository: list() / get_rows(name) / get_fields(name) / delete(name)
```
No `create`, no `write`/`append`. Everything is filename-keyed (the CSV
filename *is* the dataset's identity — no separate id).

**Analysis shape** — `application/ports/dataset_analysis_port.py`:
```
DatasetAnalysisStatus: PENDING | PROCESSING | READY | FAILED
DatasetSummaryRecord: dataset_name, status, total_rows,
  field_distributions (dict[field, dict[value, count]]),
  available_fields, uploaded_at, updated_at, error
DatasetSampleRecord: dataset_name, sample_id, + 5 fixed fields
```
Analysis is dispatched via Celery (`DatasetAnalysisDispatcher.dispatch` →
`analyze_dataset_task`) automatically on upload
(`upload_dataset.py:45`). There is **no manual "re-analyze" endpoint** today.

**The 5-field assumption.** `field_extraction.py`'s `ANALYSIS_FIELDS` is
hardcoded to `razon_marcacion`, `marcacion_final`, `integration_point`,
`tipo`, `triggered_rules` — the ARIA alert-export shape. `discover_fields()`
does exist and returns *every* column (used for `available_fields`,
consumed by Modelos' field picker), but the distribution/sampling machinery
only ever profiles those 5. This matters a lot for this feature (see §6.6).

**Storage**: `DATASET_STORAGE_BACKEND` env var, `filesystem` (default,
`DATASETS_DIR`) or `minio` (`DATASET_STORAGE_BUCKET`) — both implement the
same `DatasetRepository`/`ObjectStoragePort` pair
(`dataset_factory.py:34-38`). `list()` on both backends **reads every CSV in
full to count rows** — fine at today's scale, a real risk once "Datasets"
becomes the one place everyone loads on page-open (`datasets/
Muestra_total_ARIA.csv` alone is 180MB).

**Endpoints** (`datasets_router.py`): `GET /datasets`, `POST /datasets`
(multipart CSV upload, 202), `GET /datasets/{name}/summary`, `DELETE
/datasets/{name}`. That's the complete surface — no rows/preview endpoint,
no template endpoint, no manual analyze, no create-empty, no
extract/derive.

**Adjacent, reusable building blocks**:
- `application/use_cases/test_runs/dataset_sampling.py`'s `sample_rows()`
  already does stratified sampling — but hardcoded to the 3
  `marcacion_final` classes, not arbitrary field=value filters. The
  "extract by statistical filter" feature is a generalization of this, not
  new territory.
- `application/ports/variable_catalog_port.py`'s `VariableEntry` (flat
  catalog of variable *names*, admin-managed, already surfaced in
  Biblioteca-adjacent config screens) is the natural source for a "starter
  columns" template — it's names only, no types, but that matches the CSVs
  this system already deals in.
- `application/ports/audit_port.py`'s `AuditLogRepository` exists for
  flat per-tool-call audit logging — worth reusing for dataset mutations
  (see §7.4) rather than inventing a parallel log.

### Frontend (`frontend_mockup`)

- `biblioteca.tsx`: tabs are a plain `BibliotecaTab` union + `BIBLIOTECA_TABS`
  array (line 87-93) rendered as underlined buttons, each tab's content is
  one `activeTab === "x" && (...)` block. `"listas"` delegates entirely to a
  standalone `<WatchlistManager />` component — that's the pattern to copy:
  a self-contained `DatasetLibraryManager` component, not more inline JSX in
  `biblioteca.tsx`.
- `WatchlistManager.tsx` pattern: table + own queries/mutations + create/edit
  modal + `ConfirmDeleteDialog`, and — importantly — **doesn't load the
  heavy child data (watchlist elements) until you drill in**
  (`WatchlistElementsModal`). Same idea applies here: the Datasets tab's main
  table should show metadata only (name, rows, status, origin), not rows or
  full distributions, until you open a detail view.
- No separate top-level "Datasets" nav entry exists (`AppSidebar.tsx`) —
  confirms there's no competing IA to reconcile.
- `testing.functions.ts` already centralizes the dataset API client
  functions (`getDatasets`, `uploadDataset`, `getDatasetSummary`,
  `deleteDataset`) and `ModelFormModal.tsx` imports from there too — so
  there's already a de facto shared API module, just not a shared *UI*.
  Renaming/moving it to `lib/api/datasets.functions.ts` is a cleanup this
  work should do while touching every call site anyway.

## 3. Goals / non-goals

**Goals**
- One canonical Datasets tab in Biblioteca: list, upload, delete, visualize,
  download template, launch analysis, create-empty, create-by-extraction.
- Modelos and Testing stop owning dataset CRUD; they keep a thin picker.
- Wire up the dormant "Al dataset" alert action as a real ingestion path.
- Generalize analysis beyond the 5 hardcoded ARIA fields enough that a
  derived/empty/curated dataset with different columns doesn't silently get
  an empty distributions view.

**Non-goals (explicitly out of scope for this doc)**
- ML-based synthetic data generation (LLM- or model-generated rows). User
  confirmed "statistical extraction" means filtered stratified sampling of
  real rows, not synthesis — see §6.3.
- Row-level PII masking/anonymization policy. Flagged as a risk (§8.3) but
  not designed here — needs a security/compliance owner, not an
  engineering default.
- Dataset versioning / immutable snapshots. Progressive fill mutates a
  dataset in place; if "what did this look like on date X" ever matters,
  that's a separate versioning design.

## 4. Information architecture

```
Biblioteca
├── Conocimiento de fraude   (existing)
├── Catálogos de eventos     (existing)
├── Canales                  (existing)
├── Listas negras/blancas    (existing)
└── Datasets                 (NEW) ← DatasetLibraryManager
```

Each row in the Datasets table: name, origin badge (Subido / Vacío /
Extraído / Curado desde alertas), row count, status (PENDING/PROCESSING/
READY/FAILED), uploaded/updated at, and a row-action menu: Visualizar ·
Descargar plantilla · Analizar · Eliminar. A "Nuevo dataset" button opens a
picker between the two creation modes (§6.3/§6.4) alongside the existing
upload button.

Modelos/Testing pickers become: `<select>` of `GET /datasets` (unchanged
call) + a "Gestionar en Biblioteca" link. `NewTestRunModal`'s inline upload
button and `DatasetDetailModal`'s delete button go away — detail *viewing*
inside Testing can stay (analysts benefit from seeing distributions without
leaving the test-run flow) but becomes read-only, sourced from the same
`GetDatasetSummaryUseCase` the Biblioteca tab uses.

## 5. Data model changes

`DatasetRecord` and `DatasetSummaryRecord` need an **origin/provenance**
concept that doesn't exist today. Proposed addition (new enum, not an
overload of `DatasetAnalysisStatus` — status is about the analysis
lifecycle, origin is about how the dataset came to exist, they're
orthogonal):

```python
class DatasetOrigin(StrEnum):
    UPLOADED = "UPLOADED"        # today's only path
    EMPTY = "EMPTY"              # created via "create empty"
    EXTRACTED = "EXTRACTED"      # created via statistical extraction
    ALERT_CURATED = "ALERT_CURATED"  # first row(s) came from alert triage
```

`DatasetSummaryRecord` gains (all with defaults, appended after existing
fields — same constraint the codebase already documents for `AlertRecord`
subclasses):
```python
origin: DatasetOrigin = DatasetOrigin.UPLOADED
source_dataset_names: list[str] = field(default_factory=list)  # for EXTRACTED
extraction_filter: dict[str, str] | None = None                 # {field: value, ...}
```
A dataset's origin can be mixed after creation (an EMPTY dataset that later
gets rows appended via CSV, extraction, spreadsheet, *and* alert curation) —
`origin` records how it **started**, not an exhaustive ingestion history. If
per-append provenance ever matters, that's an audit-log concern (§7.4), not
a summary-record concern.

## 6. Feature specs

### 6.1 Upload (exists, moves)
No backend change. Frontend: move the upload control from
`NewTestRunModal` into `DatasetLibraryManager`; Testing keeps only the
picker.

### 6.2 Delete (exists, moves)
No backend change. Same move as above, out of `DatasetDetailModal` and into
the library table's row action + `ConfirmDeleteDialog` (already the
established pattern via `WatchlistManager`).

### 6.3 Create from another dataset, by statistical filter
User's spec: pick a source dataset, an AND-combination of `field = value`
filters (e.g. `marcacionA = X AND marcacionB = Y`), and a percentage; the
new dataset gets **that percentage of the filtered subset** (confirmed
choice — not a percentage of the whole source, which could raise an
`InsufficientSampleDataError`-style failure the user explicitly steered
away from).

- Generalizes `dataset_sampling.py`: needs a filter step (arbitrary
  field/value AND-match, not the hardcoded 3 `marcacion_final` classes)
  before the existing "sample N from a bucket" logic. The stratification
  machinery (largest-remainder rounding etc.) is reusable as-is once you're
  down to "sample X% of this list."
- New use case `application/use_cases/datasets/extract_dataset.py`:
  `ExtractDatasetUseCase.execute(source_names: list[str], filters:
  dict[str,str], percentage: float, target_name: str)` — reads rows via
  `DatasetRepository.get_rows` for each source (multiple sources: user's
  answer said "otro dataset o datasets", i.e. supports fan-in from more
  than one source, concatenated before filtering), filters, samples, writes
  via the new `DatasetRepository.create`/`write_rows` (§7.1), stamps
  `origin=EXTRACTED` + `source_dataset_names` + `extraction_filter`,
  dispatches analysis same as upload.
- New endpoint: `POST /datasets/extract` `{source_names, filters,
  percentage, target_name}` → 202, same shape as upload's response.
- Multi-source datasets loaded fully into memory to filter — fine for
  today's dataset sizes handled the same way `get_rows` already is; flagged
  as the same scaling risk as `list()` (§8.1), not a new one.

### 6.4 Create empty, for progressive fill
`POST /datasets/empty {name, fields: list[str]}` → writes just a CSV header
row via `DatasetRepository.create(name, fields)` (new port method, §7.1).
`origin=EMPTY`, `total_rows=0`, `status` stays `PENDING` until the first
analysis run (or is simply not analyzed until it has rows — analysis on an
empty file should short-circuit to `READY`/`total_rows=0` rather than fail).

`fields` can be typed in free-hand or pre-filled from the **variable
catalog** (§2, `VariableEntry.list(active_only=True)`) as a "start from
catalog" convenience in the creation dialog — not a hard requirement, since
the catalog is names-only and a dataset's columns may need names outside it.

**Progressive fill — 4 ingestion modes onto an existing dataset** (per
user's answer, all four apply, target dataset must already exist —
i.e. usually the EMPTY one just created, but nothing stops appending into
any dataset):

| Mode | Mechanism | New backend surface |
|---|---|---|
| CSV | re-upload against an existing name, **append** instead of overwrite | `POST /datasets/{name}/rows:csv` (multipart), reuses `DatasetRepository.append_rows` |
| Extract from other dataset(s) | same engine as §6.3, target = existing dataset instead of a new one | `POST /datasets/{name}/rows:extract` — same use case, different write path (append vs create) |
| Spreadsheet | frontend editable grid, one row at a time or pasted block | `POST /datasets/{name}/rows` `{rows: list[dict]}`, validated against the dataset's `available_fields` |
| From alert history | analyst clicks "Al dataset" on an alert (`alerta.$id.tsx`, currently a dead stub), picks a target dataset, submits | `POST /datasets/{name}/rows:from-alert` `{alert_id}` |

All four converge on one `AppendDatasetRowsUseCase` that takes already-shaped
`list[dict[str, Any]]` and does the append + re-trigger-analysis; the CSV/
extract/spreadsheet/alert paths differ only in **how rows get shaped**
before reaching it. This keeps the fan-in from 4 UI surfaces to 1 use case,
matching the hexagonal "orchestrate via ports only" rule.

**The alert-curation path is the riskiest of the four** (see §8.2) — an
`AlertRecord`'s shape is fixed application-domain fields, not arbitrary CSV
columns, so mapping alert → dataset row only works cleanly when the target
dataset's schema *is* (a subset of) the canonical alert/variable-catalog
shape. Recommend scoping this to "map by field-name intersection, warn on
alert fields the dataset doesn't have a column for, leave them out" rather
than forcing schema equality — and building it last (§9), after the other 3
modes prove out the shared append use case.

### 6.5 Visualize
Today's `DatasetDetailModal` only shows the 5-field distribution summary —
no row-level view exists anywhere. New:
- `GET /datasets/{name}/rows?offset=0&limit=50` — new port method
  `DatasetRepository.get_rows_page(name, offset, limit)` (or a thin
  slice over today's `get_rows` initially, paginated at the use-case layer
  — real streaming/seeking is a later optimization, see §8.1).
- Frontend: a paginated table in the dataset detail view, columns = the
  dataset's `available_fields`. Distributions view stays as-is alongside it
  (two tabs inside the detail modal/page: "Resumen estadístico" /
  "Filas").

### 6.6 Download template
Two distinct things both called "plantilla" by the user — worth splitting
explicitly rather than building one thing that half-serves both:
1. **Per-dataset schema template**: `GET /datasets/{name}/template` →
   CSV with just the header row (`available_fields`), for "I want to
   prepare a CSV shaped like this dataset to append later." Trivial, reuses
   `get_fields`.
2. **Blank starter template** (no source dataset yet, used from the
   "create empty" dialog): header row built from the variable catalog's
   active entries. `GET /datasets/template/default`.

Both are direct CSV downloads (`Content-Disposition: attachment`), no new
domain concept.

### 6.7 Launch statistical analysis (on demand)
Today analysis only runs automatically on upload. Progressive fill needs a
manual trigger so an analyst can refresh distributions after appending a
batch, without re-uploading. `POST /datasets/{name}/analyze` → same
`DatasetAnalysisDispatcher.dispatch`, wrapped in a tiny new use case (or
just exposed as an endpoint calling the existing dispatcher directly — no
new business logic, just a missing entry point).

## 7. Backend changes, mapped to CLAUDE.md conventions

### 7.1 `DatasetRepository` port grows (same Protocol, no new port type)
```python
class DatasetRepository(Protocol):
    def list(self) -> list[DatasetRecord]: ...
    def get_rows(self, name: str) -> list[dict[str, Any]]: ...
    def get_rows_page(self, name: str, offset: int, limit: int) -> tuple[list[dict], int]: ...  # NEW
    def get_fields(self, name: str) -> list[str]: ...
    def create(self, name: str, fields: list[str]) -> None: ...           # NEW — header-only
    def append_rows(self, name: str, rows: list[dict[str, Any]]) -> int: ...  # NEW — returns new total
    def delete(self, name: str) -> None: ...
```
Both `FilesystemCsvDatasetRepository` and `MinioCsvDatasetRepository`
implement the 3 new methods — same pattern as today, no new adapter class.

### 7.2 New use cases (`application/use_cases/datasets/`)
`create_empty_dataset.py`, `extract_dataset.py`, `append_dataset_rows.py`,
`analyze_dataset_on_demand.py` (or fold into existing `analyze_dataset.py`
as a second entry point), `get_dataset_rows.py`, `get_dataset_template.py`.
Each takes ports only, per the "application never imports infrastructure"
rule — no code shown here since this is a design doc, not an implementation
plan.

### 7.3 Router + factory
New routes on `datasets_router.py`: `POST /datasets/empty`, `POST
/datasets/extract`, `POST /datasets/{name}/rows` (+ `:csv`/`:extract`/
`:from-alert` variants or a single endpoint branching on a `source` field —
lean toward one endpoint with a discriminated body, fewer routes to wire),
`GET /datasets/{name}/rows`, `GET /datasets/{name}/template`, `GET
/datasets/template/default`, `POST /datasets/{name}/analyze`. Each gets a
`get_x_use_case()` factory function in `dataset_factory.py`, wired via
`Depends()` at the router — no deviation from existing conventions.

### 7.4 Audit trail
Dataset mutations (create-empty, extract, append, delete) are exactly the
shape `application/ports/audit_port.py`'s `AuditLogRepository` already
covers (flat per-tool-call log) — recommend wiring these calls to record
audit entries, since "who added which alerts to which training dataset" is
the kind of thing a fraud-model governance review will ask for later.
Explicitly not merging `audit_port` with `monitoring_port` (per CLAUDE.md's
existing warning) — this is audit logging, not span/CoT tracing.

## 8. Risks and challenges

### 8.1 `list()` reads every CSV in full — gets worse, not better
Both storage backends compute `row_count` by reading the entire file on
every `list()` call. The Datasets tab makes this the *default landing
view* of a page people will open often, and every new dataset (extracted
subsets, empty-then-filled ones) adds to the list. At today's one 180MB
file this is a known-tolerable cost; centralizing dataset management is
exactly the change that increases how often that cost is paid. Recommend
caching `row_count` in the summary record (already tracked there as
`total_rows`, just needs to become the read path for `list()` instead of
`DatasetRecord.row_count` from a fresh file scan) as part of this work, not
deferred — it's a small change riding along naturally with the other
`DatasetRepository` edits in §7.1.

### 8.2 Alert → dataset schema mapping is genuinely unresolved
Covered in §6.4 — flagging again here because it's the one feature with no
existing analogue anywhere in the codebase to generalize from (unlike
extraction, which generalizes `dataset_sampling.py`). Recommend building it
last and validating the mapping approach with an analyst before investing
in UI polish.

### 8.3 PII / sensitive data now gets a bigger, more discoverable surface
`Muestra_total_ARIA.csv` and any dataset extracted from it carries real
fraud-alert data (customer transactions, flagged reasons). A centralized
Biblioteca tab makes datasets easier to find, download templates from, and
extract subsets of — all reasonable asks, but worth an explicit sign-off
that "download template" (header-only) never accidentally becomes "download
data," and that the extraction feature can't be used to exfiltrate an
arbitrarily large slice under the guise of a "5% sample." Suggest a
server-side cap on extraction/preview row counts regardless of what
`percentage` requests, but this is a policy call, not just an engineering
one.

### 8.4 Generalizing analysis beyond 5 fields is a prerequisite, not a nice-to-have
Any `EMPTY`/`EXTRACTED`/`ALERT_CURATED` dataset whose columns don't include
`razon_marcacion`/`marcacion_final`/etc. gets an analysis run that computes
distributions for fields that don't exist — `field_distributions` comes
back empty, and the existing `DatasetDetailModal` UI (which hardcodes
`DATASET_FIELD_LABELS` for those 5) shows nothing useful. Recommend
`compute_distributions` take `available_fields` (or all fields under a
cardinality threshold, e.g. ≤50 distinct values) instead of the fixed
`ANALYSIS_FIELDS` tuple, keeping the 5 ARIA fields as defaults/first-class
only for backward-compatible labeling in the UI, not as a hard limit on
what gets profiled. Without this, "visualizar" and "lanzar análisis
estadístico" on any dataset that isn't upload-shaped-like-Muestra_total
delivers an empty screen.

### 8.5 Concurrent progressive-fill writes
Four independent UI surfaces (CSV, extraction, spreadsheet, alert-curation)
can append to the same dataset. Filesystem/MinIO CSV append is not
naturally atomic under concurrent writers. Given this is an internal
analyst tool (not high-concurrency), a simple per-dataset lock (or
"last-write-wins with a warning if `updated_at` changed since you loaded
the page") is enough — flagging so it's a conscious choice, not an
oversight.

## 9. Phased rollout

| Phase | Scope | Why this order |
|---|---|---|
| **1 — Centralize** | New `DatasetLibraryManager` tab wired to existing 4 endpoints; strip upload/delete out of Testing/Modelos into a read-only picker; fix `list()` to use cached `total_rows` (§8.1) | Zero new backend concepts, immediate de-duplication, fixes a scaling issue before adding more load |
| **2 — Inspect & template** | Row pagination (§6.5), per-dataset + default template downloads (§6.6), on-demand analyze (§6.7) | Additive, low-risk, no new domain concepts beyond pagination |
| **3 — Generalize analysis** | §8.4's field-agnostic distributions | Prerequisite for phases 4-5 to be useful, do before building more dataset *creation* paths |
| **4 — Create empty + CSV/spreadsheet/extraction fill** | §6.3, §6.4 (3 of 4 ingestion modes) | New write paths on `DatasetRepository`, but all still "structured data in, structured data out" |
| **5 — Alert-curated ingestion** | Wires up the dormant `alerta.$id.tsx` stub | Most novel mapping problem (§8.2), least precedent — validate the approach with an analyst before building |

## 10. Explicit decisions already made (from discussion)

- Statistical "synthetic" creation = stratified filter+sample of **real**
  rows, not ML/LLM generation.
- New datasets (empty, extracted) live in the same storage backend already
  selected via `DATASET_STORAGE_BACKEND` — no new backend, no per-type
  branching.
- This is full-stack: new backend ports/use cases/endpoints are in scope,
  not just a frontend reshuffle.
- Extraction percentage is computed **over the filtered subset**, not the
  whole source dataset.

**Proposed, not yet confirmed by the user** — flagging separately from the
list above since these are this document's own inferences, not things said
in discussion:
- Progressive fill covering all 4 modes (CSV, cross-dataset extraction,
  spreadsheet, alert-curation). The user only asked for "datasets vacíos
  para llenado progresivo" without specifying mechanism; the 4-mode split
  comes from generalizing the found-but-dead "Al dataset" stub
  (`alerta.$id.tsx:664-666`) plus the obvious CSV/extraction/manual-entry
  paths. Worth confirming before Phase 4/5 — see §11.

## 11. Open questions still worth a explicit answer before Phase 4/5

1. §8.3 — is there a hard cap on extraction/preview row counts regardless
   of requested percentage, and if so, who sets that number?
2. §8.4's cardinality threshold for "which fields get profiled" — arbitrary
   default (50) proposed, needs a sanity check against real dataset shapes.
3. §6.4's alert→dataset mapping strategy (field-name intersection with
   warnings) — needs an analyst's confirmation that's actually useful
   before Phase 5 is built.
