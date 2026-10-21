# Capture the production jam demo

This directory is reserved for real screenshots. No captures are included yet.
The helper prepares the running platform; take the screenshots with your browser
or operating system's capture tool.

## Prepare

From the repository root, with Docker running and Python 3 available:

```bash
./scripts/demo_screenshots.sh jam
```

Windows PowerShell:

```powershell
./scripts/demo_screenshots.ps1 jam
```

The helper runs `docker compose up -d --build`, restores a normal baseline through
`labctl`, waits for fresh telemetry and video, records another 15 seconds of
normal operation, and injects `jam`. It then waits for CV/ML anomalies and the
ProductionLineBlocked, ComputerVisionAnomaly and MLAnomaly alerts to be active in
Alertmanager and delivered to the incident receiver. Each readiness check has a
120-second timeout and fails with a nonzero exit code rather than claiming success.
The first build can take longer. The jam remains active for capture.

On macOS, append `--open` to the shell command to open the four printed URLs.
This option only launches browser URLs; it does not log in, control the browser
or capture images. On other platforms it prints a manual-opening message.

## Capture

| File | Open | Capture guidance |
|---|---|---|
| `camera-jam.png` | http://localhost:8888/line1/ | Wait for HLS playback; show the red obstruction on the conveyor and the JAM label. |
| `grafana-jam.png` | http://localhost:3000 | Sign in with `admin` / `admin`. Open **Industrial Computer Vision & OT Lab**. Set **Last 5 minutes**, refresh, and capture the Factory Process, Computer Vision and Machine Learning panels. Use a full-page capture or browser zoom if needed. |
| `alertmanager-jam.png` | http://localhost:9093 | Show the active jam, CV and ML alerts. Expand relevant alert groups so their names and labels are readable. |

For Grafana, include the blocked line, conveyor speed drop, increased vibration,
reduced quality and CV/ML anomaly states. Let the jam run for another 30–60 seconds
if you want a longer plateau in the charts. The charts record real samples; do not
alter values or composite a fabricated dashboard.

The incident receiver at http://localhost:8090/alerts provides a supporting check
that firing notifications arrived. It does not need a separate screenshot.

Save the three PNG files in this directory using the exact filenames above.
Then remove the HTML comment around the prepared gallery in the root README's
**Demo** section. Replace the temporary capture checklist and pending-images note
with that gallery. The relative image links are already written.

## Restore

```bash
./scripts/demo_screenshots.sh normal
```

Or run `./scripts/demo_screenshots.ps1 normal` in PowerShell. The helper restores
normal process/image state and both edge OT connections. Allow the normal alert
resolution delay before expecting firing notifications to disappear. If preparation
was interrupted, the same command restores the platform; it does not delete data.
