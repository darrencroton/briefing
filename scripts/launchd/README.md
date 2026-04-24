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
uv run briefing watch --once --dry-run
```

The selected LLM CLI must already be authenticated for non-interactive use before you install the batch LaunchAgent. The selected `noted` CLI in `user_config/settings.toml` must already be permissioned and usable before you install the watch LaunchAgent.

## Batch `briefing run`

This keeps the existing pre-meeting note refresh flow.

### Render the plist

```bash
./scripts/launchd/render-plist.sh
```

The rendered file is written to:

```text
tmp/launchd/com.user.briefing.plist
```

It includes the absolute `uv` path, repo root, log directory, and the current shell `PATH`.

### Install the LaunchAgent

```bash
./scripts/launchd/install-plist.sh
```

### Trigger a run immediately

```bash
launchctl kickstart -k gui/$(id -u)/com.user.briefing
```

## Long-running `briefing watch`

This installs the separate Meeting Intelligence watcher. It plans eligible sessions, keeps pre-written next manifests fresh, and invokes `noted start --manifest` at pre-roll.

### Render the plist

```bash
./scripts/launchd/render-watch-plist.sh
```

The rendered file is written to:

```text
tmp/launchd/com.user.briefing-watch.plist
```

### Install the LaunchAgent

```bash
./scripts/launchd/install-watch-plist.sh
```

### Restart the watcher

```bash
launchctl kickstart -k gui/$(id -u)/com.user.briefing-watch
```

## Inspect logs

```bash
tail -n 50 logs/last-run.log
tail -n 50 logs/launchd.stdout.log
tail -n 50 logs/launchd.stderr.log
tail -n 50 logs/launchd-watch.stdout.log
tail -n 50 logs/launchd-watch.stderr.log
```

## Update the job

If you move this repo or your `uv` path changes, rerun `render-plist.sh` and reinstall.
