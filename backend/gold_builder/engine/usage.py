"""Per-job usage aggregation + budget enforcement.

The router calls `record(job_id, resp.usage, provider, model)` after every
LLM completion. `check_budget(job_id, config)` raises `BudgetExceededError`
when a job exceeds its configured caps.

Budgets are configuration only — do NOT require paid providers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from ..models import UsageBudget, UsageMetrics


class BudgetExceededError(RuntimeError):
    pass


class UsageTracker:
    def __init__(self):
        self._by_job: Dict[str, UsageMetrics] = {}
        self._budget_by_job: Dict[str, UsageBudget] = {}

    def set_budget(self, job_id: str, budget: UsageBudget) -> None:
        self._budget_by_job[job_id] = budget

    def get_budget(self, job_id: str) -> Optional[UsageBudget]:
        return self._budget_by_job.get(job_id)

    def get(self, job_id: str) -> UsageMetrics:
        return self._by_job.get(job_id) or UsageMetrics()

    def record(
        self,
        job_id: str,
        usage: Optional[dict],
        provider: str,
        model: str,
    ) -> UsageMetrics:
        m = self._by_job.setdefault(job_id, UsageMetrics())
        m.calls += 1
        u = usage or {}
        # Accept common shapes
        prompt = int(u.get("prompt_tokens") or u.get("input_tokens") or 0)
        completion = int(u.get("completion_tokens") or u.get("output_tokens") or 0)
        m.prompt_tokens += prompt
        m.completion_tokens += completion
        m.total_tokens = m.prompt_tokens + m.completion_tokens
        m.by_provider[provider] = m.by_provider.get(provider, 0) + 1
        m.by_model[model] = m.by_model.get(model, 0) + 1
        self._by_job[job_id] = m
        return m

    def check_budget(self, job_id: str) -> None:
        b = self._budget_by_job.get(job_id)
        if not b:
            return
        m = self._by_job.get(job_id) or UsageMetrics()
        if b.max_calls is not None and m.calls >= b.max_calls:
            raise BudgetExceededError(
                f"job {job_id} exceeded max_calls={b.max_calls}"
            )
        if b.max_total_tokens is not None and m.total_tokens >= b.max_total_tokens:
            raise BudgetExceededError(
                f"job {job_id} exceeded max_total_tokens={b.max_total_tokens}"
            )
        if b.max_prompt_tokens is not None and m.prompt_tokens >= b.max_prompt_tokens:
            raise BudgetExceededError(
                f"job {job_id} exceeded max_prompt_tokens={b.max_prompt_tokens}"
            )
        if b.max_completion_tokens is not None and m.completion_tokens >= b.max_completion_tokens:
            raise BudgetExceededError(
                f"job {job_id} exceeded max_completion_tokens={b.max_completion_tokens}"
            )

    def clear(self, job_id: str) -> None:
        self._by_job.pop(job_id, None)
        self._budget_by_job.pop(job_id, None)


tracker = UsageTracker()
