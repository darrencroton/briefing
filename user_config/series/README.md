# Series Configuration

Each file in this directory defines one meeting series.

## Required fields

- `series_id`
- `display_name`
- `note_slug`
- `match`

## Match keys

- `title_any`
- `attendee_emails_any`
- `organizer_emails_any`
- `calendar_names_any`

All populated match keys must match for the series to be selected.

## Source keys

- `slack.channel_refs`
- `slack.dm_user_ids`
- `notion`
- `files`

Example configuration is provided in [example-team-weekly.yaml](/Users/dcroton/Local/git-repos/briefing/user_config/series/example-team-weekly.yaml).

