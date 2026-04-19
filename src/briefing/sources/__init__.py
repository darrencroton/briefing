"""Source collection orchestration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from logging import Logger

from .email_source import collect_email_sources
from .file_source import collect_file_source
from .notion_source import collect_notion_source
from .previous_note import collect_previous_note
from .slack_source import collect_slack_sources
from .types import SourceContext
from ..models import SourceResult
from ..settings import AppSettings


def collect_sources(
    settings: AppSettings,
    event,
    series,
    logger: Logger,
    env: dict[str, str],
) -> list[SourceResult]:
    """Collect all configured sources in bounded parallelism."""
    context = SourceContext(
        settings=settings,
        event=event,
        series=series,
        logger=logger,
        env=env,
    )
    jobs: list[tuple[int, callable]] = [(0, lambda: [collect_previous_note(context)])]
    order = 1

    if series.sources.slack and (
        series.sources.slack.channel_refs or series.sources.slack.dm_conversation_ids
    ):
        token = env.get("SLACK_USER_TOKEN", "")
        jobs.append(
            (
                order,
                lambda token=token, cfg=series.sources.slack: collect_slack_sources(
                    context,
                    cfg,
                    token,
                ),
            )
        )
        order += 1

    for notion_config in series.sources.notion:
        jobs.append(
            (
                order,
                lambda cfg=notion_config, token=env.get("NOTION_TOKEN", ""): [
                    collect_notion_source(context, cfg, token)
                ],
            )
        )
        order += 1

    for file_config in series.sources.files:
        jobs.append((order, lambda cfg=file_config: [collect_file_source(context, cfg)]))
        order += 1

    if series.sources.emails:
        jobs.append(
            (order, lambda cfgs=series.sources.emails: collect_email_sources(context, cfgs))
        )
        order += 1

    results_by_order: list[tuple[int, list[SourceResult]]] = []
    with ThreadPoolExecutor(max_workers=settings.execution.max_parallel_sources) as executor:
        futures = [(order_value, executor.submit(job)) for order_value, job in jobs]
        for order_value, future in futures:
            try:
                results = future.result(timeout=settings.execution.source_timeout_seconds)
            except Exception as exc:  # pragma: no cover - defensive wrapper
                results = [
                    SourceResult(
                        source_type="internal",
                        label="Internal source error",
                        content="",
                        required=True,
                        status="error",
                        error=str(exc),
                    )
                ]
            results_by_order.append((order_value, results))

    flattened: list[SourceResult] = []
    for _, results in sorted(results_by_order, key=lambda item: item[0]):
        flattened.extend(results)
    return flattened
