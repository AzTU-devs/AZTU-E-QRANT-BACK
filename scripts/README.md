# One-off data scripts

Follow-ups to the security work. Each is **idempotent** and safe to re-run.

**Do not run against production without a backup and a read of the output
first.** Two of the three only *report* — they change nothing. Run them from the
backend root with the app's virtualenv so the `.env` / DB config is loaded:

```bash
venv/bin/python -m scripts.resanitize_announcements   # WRITES (re-sanitises HTML)
venv/bin/python -m scripts.report_smeta_mismatches     # read-only report
venv/bin/python -m scripts.report_project_cap_overrides # read-only report
```

`resanitize_announcements` prints what it would change and only writes when run
with `--apply`; without it, it is a dry run.
