# Incident Management upgrade — validation record

Date: 2026-10-21. Local macOS ARM64 host with Docker Desktop, Linux/aarch64
containers and Python 3.12. PostgreSQL 18.6, SQLAlchemy 2.1.6, Psycopg 3.3.6,
Jinja2 3.1.6. Runtime has no incident SaaS, paid API or generative model.

## Implementation

The existing `incident-receiver` is extended in place. The legacy `POST /webhook`
and `GET /alerts` contracts remain usable by Alertmanager, the original scenario
runner and screenshot helper. The portal is at **http://localhost:8090/**;
active incidents, history and statistics are at `/incidents`, `/history` and
`/statistics`. Interactive OpenAPI documentation is at `/docs`, using vendored Swagger UI
5.34.0 assets and its retained upstream license; no CDN or remote validator is used.

Business tables: `incidents`, `alert_occurrences`, `incident_events`, `signals`,
`incident_evidence`, `incident_reports`. `schema_migrations` tracks the initial
versioned, transactional migration. Database startup/migration is automatic;
`incident-db-data` is a named persistent Docker volume. PostgreSQL is connected
only to internal `incident_net`, without published host ports.

A stored `DETECTED` event opens an incident in FIRING. Supported operator states
are FIRING, ACKNOWLEDGED, INVESTIGATING, MITIGATED and RESOLVED, with validated
and idempotent transitions. Human status is independent of source-alert state.
Manual resolution requires every underlying alert to recover. Default automatic
resolution waits 30 seconds after all source alerts recover; negative
`INCIDENT_AUTO_RESOLVE_SECONDS` disables that policy. No invented acknowledgement
or mitigation timestamp is inserted during automatic closure.

MTTA is acknowledgement minus detection; MTTR is resolution minus detection.
Duration starts at the earliest correlated Alertmanager startsAt. Database
averages exclude missing acknowledgements/unresolved incidents rather than
pretending they were zero-duration responses.

Correlation is deterministic, site/line scoped, and uses a configurable 90-second
alert-start window. A blocked-sensor anchor joins compatible jam symptoms and can
promote/merge earlier symptom incidents without losing their history or operator
notes. Explicit non-red camera degradation stays separate. ML symptoms can join
specific process incidents, stale telemetry can join PLC connectivity, and recent
independent healthy probes can support edge-path attribution. Service incidents
are separated by affected job/instance. Closed incidents stay closed; new source
start epochs create new incidents. Deduplication ignores provisional firing
endsAt changes and is serialized transactionally across PostgreSQL connections.

MQTT and a local Prometheus query enrich evidence only. Latest samples are
coalesced in a bounded buffer, stored at most once per source/scope every 10s,
and attached within a 30s source-age window. The initial and recovered payloads
remain timestamped in incident history. Runbooks are deterministic demonstration
guidance, distinct from actual operator actions and approved site safety procedures.

Final reports are generated at closure from stored incident fields, alert
occurrences, evidence and timeline, as immutable JSON plus Markdown snapshots.
`GET /api/incidents/{id}/report` and `/report.md` return them; an open incident
returns HTTP 409. Root cause, impact, actions and resolution notes can be edited
before closure via `PATCH /api/incidents/{id}`.

Other APIs: `GET /api/incidents` (filters/pagination), `GET /api/incidents/{id}`,
`POST /api/incidents/{id}/acknowledge`, `/investigate`, `/mitigate`, `/resolve`,
and `GET /api/statistics`. `/healthz` is liveness; `/readyz` checks initialized
storage. Webhook database failures return HTTP 503 for Alertmanager retry.

## Files changed

| Files | Purpose |
|---|---|
| `services/incident_receiver/main.py` | Compatible webhook/alert API, lifecycle API, readiness and portal routes |
| `services/incident_receiver/models.py`, `migrations.py`, `store.py` | Normalized persistent schema, versioned migration, transactions, correlation, lifecycle and SQL statistics |
| `services/incident_receiver/rules.py`, `reports.py` | Explicit category/severity/runbook rules and deterministic final exports |
| `services/incident_receiver/enrichment.py`, `metrics.py` | Bounded actual-source evidence, monitoring facts and database-derived Prometheus metrics |
| `services/incident_receiver/templates/`, `static/` | Local Jinja2 portal, responsive CSS, real API action buttons and note preservation |
| `docker-compose.yml`, `.env.example`, `requirements.txt` | PostgreSQL/internal network/volume, demo environment settings and pinned Python dependencies |
| `.github/workflows/ci.yml`, `tests/test_incidents.py` | Isolated SQLite unit/API tests and actual temporary PostgreSQL-schema persistence/concurrency test |
| `tools/smoke_test.py`, `scripts/validate.py` | Portal/database/report compatibility checks and required-file/network validation |
| `scripts/incident_integration_test.py`, `Makefile` | Real scenario, workflow, report and restart validation targets |
| `scripts/demo_screenshots.py` | Link existing screenshot preparation to the operational portal |
| `prometheus/rules.yml`, `grafana/dashboards/computer-vision.json` | Storage alert, six compact incident panels and cross-links; original panels/rules retained |
| `README.md`, `SOURCES.md`, validation records | Architecture, lifecycle, correlation policy, API/demo commands, upstream references and results |

## Checks executed

- Python syntax/AST, YAML, JSON, shell syntax, localhost bindings, expected services,
  internal database network and no published database port: passed.
- Docker Compose configuration, all final image builds and installed dependency
  consistency (`pip check`): passed.
- PostgreSQL initialization and automatic migration 1: passed; readiness healthy.
- Final complete smoke test passed: secure OPC-UA reads, MQTT telemetry/ML/CV/YOLO,
  raw RTSP/HLS, annotated JPEG/MJPEG, database/portal/API, Prometheus probes,
  Grafana provisioning and Alloy-to-Loki logs.
- Full test suite: **50 passed**, including the original CV/ML/YOLO tests and the
  actual PostgreSQL persistence/concurrent deduplication test. PostgreSQL fixtures
  are isolated in a random temporary test schema which is dropped afterward;
  they never enter operational incident history.
- Prometheus config and all **14 alert rules**: passed. Alertmanager config: passed.
- Real incident scenarios passed: jam, overheat, vibration, quality-drop,
  dark-camera, camera-offline, OPC-UA-down and edge-OT-cut. Each incident retained
  its source history and returned a final JSON/Markdown report after normal recovery.
- Jam grouped all five actual blocked/CV/vibration/quality/ML alerts into one
  Production Line Jam, with actual blocked PLC and red-obstruction evidence.
  Acknowledge/investigate/mitigate timestamps and notes were persisted.
- Restarting the incident service retained the incident number and timeline;
  restarting the entire Compose stack retained the exact immutable jam report.
- Real Chrome acknowledge, investigate, save notes, mitigate and resolve buttons
  passed against an actual camera-outage incident. Edited notes also survived
  workflow navigation without a separate Save click on a real OT-network incident.
- Additional actual camera and PLC outages confirmed that exporter, endpoint and
  stream/read-loss alerts join the same canonical outage incident under the final rules.
- Actual PostgreSQL stop/start returned readiness HTTP 503 with liveness HTTP 200;
  restarting storage restored readiness and the exact existing report.
- Interactive API documentation executed a real GET statistics request using
  only local resources. Browser history filters and Markdown report download passed;
  the browser observed no external HTTP requests or JavaScript errors.
- Actual Chrome desktop and mobile rendering: passed for overview, active/history,
  statistics and a real incident detail; no JavaScript page errors or mobile overflow.

## Grafana and metrics

The new Incident Management row includes active, total and resolved canonical
incidents, mean MTTA, mean MTTR and database readiness. Missing response samples
remain empty in the corresponding Grafana queries. The previous alert-occurrence
panel remains, with a corrected title; the dashboard links to the Incident Portal,
and the portal links back to Grafana, Prometheus, Alertmanager and camera views.

Metrics include `incident_total`, `incident_active_total`, `incident_resolved_total`,
`incident_mtta_seconds`, `incident_mttr_seconds`, `incident_acknowledged_total`,
`incident_database_ready`, `incident_by_severity`, `incident_by_type`,
`incident_by_status`. These are database-derived gauges, including names ending
in `_total`: canonical counts can decrease during correlation merges. Existing
`incident_active_alerts` and notification counters are preserved. Metric labels
are bounded severity/type/status values; incident numbers/IDs never become labels.
`IncidentDatabaseUnavailable` waits 15s before alerting when storage is unavailable.

The platform was left running in **normal** state with no active incidents. At
final inspection PostgreSQL retained **12 canonical resolved incidents**, all from
actual controlled scenarios/associated platform alerts, plus their evidence and
reports. These counts are a validation observation, not seeded application data.

## Limitations

- Local unauthenticated demonstration UI/API, development-only environment credentials.
  Production needs authentication/RBAC, managed secrets, backups/retention and approved
  operational/safety procedures. The portal is not a safety interlock.
- Deterministic temporal correlation is a useful heuristic, not proof of physical
  causality; suggestions remain separate from operator-confirmed root cause.
- MQTT evidence is sampled/coalesced, not a complete lossless stream. Alertmanager
  delivery retries protect primary notifications during storage failures; intermediate
  enrichment samples can be omitted during outages.
- There is no automatic historical retention/deletion job; stored incident reports
  remain until the database volume is deliberately deleted or externally managed.
- The previous in-memory receiver did not provide durable pre-upgrade history.
- Chrome was tested locally on macOS ARM64. Native Windows/PowerShell and amd64
  execution were not run here. CI configuration includes its own PostgreSQL service,
  but the updated GitHub Actions job has not yet run on GitHub.
- The upstream Starlette TestClient/httpx deprecation warning remains non-fatal
  with the project's existing pinned test dependencies.

## Reproduce

```bash
docker compose up -d --build
make validate
make test
make incident-db-test
make normal
make smoke
make incident-test
# Optional full-stack restart check:
python3 scripts/incident_integration_test.py --quick --restart-stack
```

For the primary demonstration:

```bash
./scripts/labctl.sh jam
# Open http://localhost:8090/ and inspect Production Line Jam.
# Acknowledge, investigate and record actual notes/actions in the portal.
./scripts/labctl.sh normal
# After alert recovery + the quiet period, open /history and download the final report.
```
