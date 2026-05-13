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

If you use `noted` ad hoc recordings, expose this repo's `briefing` executable so `noted` can run `briefing session-ingest` after completion:

```bash
mkdir -p "$HOME/.local/bin"
ln -sf "$PWD/.venv/bin/briefing" "$HOME/.local/bin/briefing"
which briefing
```

You can instead set `briefing_command` in `~/Library/Application Support/noted/settings.toml` to the absolute path of `.venv/bin/briefing`.

## Batch `briefing run`

This keeps the existing pre-meeting note refresh flow.

### Install

```bash
./scripts/launchd/install-plist.sh
```

The installer renders the plist, validates it, copies it to
`~/Library/LaunchAgents/com.user.briefing.plist`, reloads the job, and enables
it.

### Trigger a run immediately

```bash
launchctl kickstart -k gui/$(id -u)/com.user.briefing
```

## Long-running `briefing watch`

This installs the separate Meeting Intelligence watcher. It plans eligible sessions, keeps pre-written next manifests fresh, and invokes `noted start --manifest` at pre-roll.

The watcher reloads `user_config/settings.toml` at each poll, so normal settings
edits do not require a LaunchAgent restart. If the file is temporarily invalid
while being edited, that poll is skipped and the watcher tries again on the next
poll.

### Install

```bash
./scripts/launchd/install-watch-plist.sh
```

The installer renders the plist, validates it, copies it to
`~/Library/LaunchAgents/com.user.briefing-watch.plist`, reloads the job, and
enables it.

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

Use the uninstall scripts to stop loaded jobs and move installed plists from
`~/Library/LaunchAgents` into `archive/launchd/`.

```bash
# Uninstall all briefing LaunchAgents.
./scripts/launchd/uninstall-all.sh

# Or uninstall one job.
./scripts/launchd/uninstall-plist.sh
./scripts/launchd/uninstall-watch-plist.sh
```

To stop a job without uninstalling it, use `bootout`. This matters for the
watcher because `com.user.briefing-watch` has `KeepAlive` enabled; killing the
process directly can let `launchd` restart it.

```bash
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.user.briefing.plist"
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

If you move this repo or your `uv` path changes, rerun the relevant install
script. It will regenerate and reload the plist.
