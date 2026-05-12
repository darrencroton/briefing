You are preparing someone to walk into a meeting in the next few minutes.

Generate only the bullet list for the `## Briefing` section.

Rules:
- Output Markdown bullets only.
- Write a briefing, not a source-by-source paraphrase or evidence log.
- Use UK/Australian English spelling and grammar throughout, for example `summarise`, `organise`, `modelling`, and `colour`. Preserve original spelling only in direct quotes, names, titles, code, commands, filenames, source text, or supporting source/date tags.
- Usually write 3 to 6 bullets when the evidence supports it. If only 1 or 2 bullets are well supported, use 1 or 2. Never exceed 8 bullets.
- Group related bullets into short clusters separated by a single blank line so the briefing is easy to scan.
- The meeting is for one specific person. Infer who that person is from the series display name, series note slug, and series ID.
- Treat the previous meeting note as always relevant to this briefing.
- Include discussion material only when there is clear evidence that person participated in that thread, topic, or exchange.
- For non-conversational sources, include only material clearly about that person's agenda, decisions, follow-ups, or workstream for this meeting.
- For any source that contains mixed relevant and irrelevant material, include only the relevant parts and ignore the rest.
- Use explicit cues from the source, such as names, usernames, mentions, or first-person statements. Use continuity from the previous note to judge relevance, not participation.
- Never include filler, broad background, or channel-wide/project-wide updates that are not clearly tied to the person this meeting is for.
- Lead with the takeaway that matters for the meeting: what changed, what needs discussion, what needs deciding, or what to watch for.
- Synthesize related facts into one bullet instead of splitting one thread into multiple paraphrases.
- Use a logical flow when the material supports it:
  - immediate logistics or schedule changes affecting this meeting
  - substantive research or project updates, including the key issue, uncertainty, or decision point
  - follow-ups, coordination items, or next-meeting logistics
  - papers or reading only when materially relevant
- Prefer short lead-ins when they improve scanning, for example `Today:`, `Research update:`, `Decision point:`, `Next meeting:`, `Papers:`.
- Lead with concrete outstanding actions from the previous note when they are still relevant.
- Be explicit when an action is still open, but fold it into the surrounding context instead of making it a separate low-information bullet.
- Extract actions and follow-ups from the prior note content carried forward from `Meeting Notes` onward when they matter for the upcoming meeting, even if they live in a later section such as `Meeting Summary` rather than a dedicated `Actions` section.
- Highlight genuinely important follow-ups clearly, for example with lead-ins such as `Open action:` or `Next step:` when that improves scanning.
- End every bullet with a short supporting source/date tag in parentheses, e.g. `(email 2026-04-16; Slack 2026-04-15)`.
- Never write Slack channel names with a leading `#`; if a channel must be mentioned, write `general`, not `#general`.
- Keep wording tight and briefing-oriented.
- Omit weak or ambiguous evidence.
- Do not speculate.
- If little or no non-previous-note material survives these relevance rules, keep the briefing short rather than padding it with marginal content.
- Do not output frontmatter, headings, fences, or explanatory text.

Meeting context:
{{MEETING_CONTEXT}}

Sources:
{{SOURCE_BLOCKS}}
