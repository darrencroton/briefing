# Automating `briefing` with `launchd`

This guide is only for automation setup.

Do the base onboarding first:

- [`README.md`](../../README.md)
- [`docs/setup-and-configuration-walkthrough.md`](../../docs/setup-and-configuration-walkthrough.md)
- [`docs/source-guides/README.md`](../../docs/source-guides/README.md)

Only install automation after these manual checks succeed:

```bash
./scripts/setup.sh
uv run briefing validate
uv run briefing run
```

The selected LLM CLI must already be authenticated for non-interactive use before you install the LaunchAgent.

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
