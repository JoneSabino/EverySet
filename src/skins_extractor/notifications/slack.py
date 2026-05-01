"""Slack webhook notification stub."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def notify_pending_patterns(
    webhook_url: str,
    pattern_count: int,
    document_name: str,
) -> None:
    if not webhook_url:
        logger.debug("No Slack webhook configured — skipping notification")
        return

    payload = {
        "text": (
            f":mag: *Skins Extractor* — {pattern_count} new pattern(s) pending review "
            f"from `{document_name}`.\n"
            f"Run `skins patterns list --status pending_review` to review."
        )
    }

    try:
        import httpx

        resp = httpx.post(webhook_url, json=payload, timeout=5.0)
        resp.raise_for_status()
        logger.info("Slack notification sent (%d patterns)", pattern_count)
    except Exception as e:
        logger.warning("Slack notification failed: %s", e)
