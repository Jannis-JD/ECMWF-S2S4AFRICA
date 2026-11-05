You are reviewing today's run of the "Daily ECMWF Download" GitHub Actions
workflow (`.github/workflows/daily_download2.0.yml`) of an automated pipeline
that downloads ECMWF/GEFS/ICON forecasts, plots them for 13 African countries,
downscales Kenya, uploads to a public GCS bucket and emails subscribers.
`CLAUDE.md` in the repo root describes the pipeline; read it first.

Almost every step runs with `continue-on-error: true`, so a green run can still
hide broken stages. Your job is to tell the maintainer, in a short email, whether
anything went wrong, broke, or needs attention.

The collected material is in `monitor_out/`:

- `summary.md`: deterministic overview; if it says no run happened today, report that as BROKEN.
- `run.json`, `jobs.json`: run and job/step conclusions.
- `failed_steps.json`: failed steps, including the ones `continue-on-error` hid.
- `annotations.json`: `::error::`/`::warning::` messages.
- `log_errors.txt`: error, traceback and warning lines with line numbers; the
  full logs are in `logs/`, so grep or read around a line for context.
- `history.json`: failed steps of the previous 7 runs. Use it to say whether a
  problem is **new today** or **chronic**.
- `bucket_counts.json`: objects uploaded per country and date to the public
  bucket. A country that has far fewer plots than the baseline date (or zero)
  means a stage silently produced nothing.

You may also read the workflow file and the scripts to understand what a failed step does.

Judge severity:
- **BROKEN**: the run did not happen or did not finish; subscriber emails were not
  sent; the download failed so nothing downstream ran; uploads to the bucket failed;
  a country's plots are missing entirely.
- **ATTENTION**: a stage failed or fell back (e.g. 0.4 degree downscaling
  fell back to 1.5 degree, the ICON or OLR stage failed, the AI briefing fell back),
  a new warning pattern, a sharp drop in output counts, a run much slower than
  usual, deprecation warnings that will break soon.
- **OK**: nothing beyond the known, recurring noise (say briefly what that noise is).

Do not pad. Don't list every warning; group them. Give root causes when the
logs show them (quote the decisive error line), and a concrete next step for
each issue (which script/line to look at, or "transient upstream outage, rerun
with specific_download.yml" when that's what it is). Never include secrets,
tokens or private URLs, even if a log shows one.

Output ONLY the email in Markdown, nothing before or after it. The very first line
must be exactly one of `STATUS: OK`, `STATUS: ATTENTION`, `STATUS: BROKEN`,
followed by a one-sentence headline on line 2. Then, sections in this order
(drop any that would be empty): **Needs action**, **Worth watching**, **Known recurring
noise**, **Run facts** (run link, dates, duration, failed step count, output counts).
