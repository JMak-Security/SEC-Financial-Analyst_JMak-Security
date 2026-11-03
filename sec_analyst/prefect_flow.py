"""Optional Prefect orchestration for resilient scheduled SEC analysis."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from prefect import flow, task
import requests

from .agent import FinancialAnalystAgent
from .edgar import SecApiError, SecEdgarClient
from .workspace import WorkspaceManager

logger = logging.getLogger("sec_analyst.prefect")


def retry_transient_failure(task: Any, task_run: Any, state: Any) -> bool:
    failure = state.result(raise_on_failure=False)
    if isinstance(failure, SecApiError):
        return failure.retryable
    return isinstance(
        failure,
        (requests.ConnectionError, requests.Timeout, OSError, TimeoutError),
    )


@task(
    name="retrieve-validate-analyze-sec-company",
    retries=4,
    retry_delay_seconds=[5, 15, 45, 90],
    retry_jitter_factor=0.2,
    persist_result=True,
    retry_condition_fn=retry_transient_failure,
)
def analyze_company_task(
    company: str, contact_email: str, workspace_path: str, filing_count: int = 4
) -> dict[str, Any]:
    workspace = WorkspaceManager(workspace_path, create=True)
    analyst = FinancialAnalystAgent(workspace, SecEdgarClient(contact_email))
    result = asyncio.run(analyst.analyze_sec(company, filing_count))
    return result.as_dict()


def alert_on_failure(flow: Any, flow_run: Any, state: Any) -> None:
    details = {
        "flow_name": getattr(flow, "name", "SEC analysis"),
        "flow_run_id": str(getattr(flow_run, "id", "")),
        "state": str(state),
    }
    logger.error(
        "SEC financial analysis flow failed",
        extra=details,
    )
    webhook_url = os.environ.get("SEC_ALERT_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return
    try:
        response = requests.post(
            webhook_url,
            json={
                "text": (
                    f"SEC analysis flow failed: {details['flow_name']} "
                    f"(run {details['flow_run_id']}, {details['state']})"
                )
            },
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error(
            "SEC failure webhook delivery failed",
            extra={"flow_run_id": details["flow_run_id"], "error": str(exc)},
        )


@flow(
    name="sec-financial-analysis",
    description=(
        "Retrieve SEC filing facts with rate-limit retries, validate XBRL inputs, "
        "persist immutable DuckDB lineage, and publish financial health reports."
    ),
    on_failure=[alert_on_failure],
)
def analyze_company_flow(
    company: str,
    contact_email: str,
    workspace_path: str | Path,
    filing_count: int = 4,
) -> dict[str, Any]:
    return analyze_company_task(
        company, contact_email, str(workspace_path), filing_count
    )
