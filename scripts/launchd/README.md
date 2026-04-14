# Automating `briefing` with `launchd`

Only install automation after these manual checks succeed:

```bash
./scripts/setup.sh
uv run briefing validate
uv run briefing run
```

## Render the plist

```bash
./scripts/launchd/render-plist.sh
```

The rendered file is written to:

```text
tmp/launchd/com.user.briefing.plist
```

It includes the absolute `uv` path, repo root, log directory, and the current shell `PATH`.

## Install the LaunchAgent

```bash
./scripts/launchd/install-plist.sh
```

## Trigger a run immediately

```bash
launchctl kickstart -k gui/$(id -u)/com.user.briefing
```

## Inspect logs

```bash
tail -n 50 logs/last-run.log
tail -n 50 logs/launchd.stdout.log
tail -n 50 logs/launchd.stderr.log
```

## Update the job

If you move this repo or your `uv` path changes, rerun `render-plist.sh` and reinstall.
