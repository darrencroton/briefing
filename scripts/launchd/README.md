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

## Stop or uninstall a LaunchAgent

Use `bootout` to stop a loaded job. This is the right way to cancel the
long-running watcher because `com.user.briefing-watch` has `KeepAlive` enabled;
killing the process directly can let `launchd` restart it.

Uninstall all `briefing` LaunchAgents:

```bash
./scripts/launchd/uninstall-all.sh
```

The uninstall scripts stop the loaded job and move the installed plist from
`~/Library/LaunchAgents` into `archive/launchd/`.

Uninstall only the batch `briefing run` LaunchAgent:

```bash
./scripts/launchd/uninstall-plist.sh
```

Uninstall only the long-running `briefing watch` LaunchAgent:

```bash
./scripts/launchd/uninstall-watch-plist.sh
```

To stop a job without uninstalling it, run `bootout` directly.

Stop the batch `briefing run` LaunchAgent:

```bash
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.user.briefing.plist"
```

Stop the long-running `briefing watch` LaunchAgent:

```bash
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.user.briefing-watch.plist"
```

If the job is not currently loaded, `launchctl` may print an error such as
`No such process`. That is fine when your goal is only to ensure the job is not
running.

Check what `launchd` still has loaded:

```bash
launchctl print "gui/$(id -u)/com.user.briefing"
launchctl print "gui/$(id -u)/com.user.briefing-watch"
```

If a job has been stopped or uninstalled, `launchctl print` should report that
the service could not be found.

## Update the job

If you move this repo or your `uv` path changes, rerun `render-plist.sh` and reinstall.
