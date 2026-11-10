"""Run Planner -> Coder -> Reviewer once (no retries) and return one result object.

Expected failures come back as a Status + friendly message, with any partial results kept
(e.g. the outline when the Coder fails). Unexpected exceptions are bugs and propagate.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from app.coder import CoderError, write_sql
from app.llm import LLMError, LLMFn, complete
from app.planner import CannotAnswerError, PlannerError, make_plan
from app.reviewer import ReviewResult, review_sql
from app.schema import SchemaError, validate_selection


class Status(str, Enum):
    OK = "ok"
    REVIEW_FAILED = "review_failed"
    CANNOT_ANSWER = "cannot_answer"
    INPUT_ERROR = "input_error"
    CODER_ERROR = "coder_error"
    LLM_ERROR = "llm_error"


@dataclass(frozen=True)
class ChainResult:
    status: Status
    message: str | None  # friendly error text; None when ok
    columns: tuple[str, ...] = ()  # validated selection (empty on a bad selection)
    outline: str | None = None  # Planner output
    sql: str | None = None  # Coder output, as returned
    review: ReviewResult | None = None  # Reviewer verdict (errors + formatted SQL)

    @property
    def passed(self) -> bool:
        return self.status is Status.OK


def run(request: str, selected_columns: Iterable[str], llm: LLMFn = complete) -> ChainResult:
    # Validate the column selection first: no LLM call for a bad selection.
    try:
        columns = validate_selection(selected_columns)
    except SchemaError as err:
        return ChainResult(Status.INPUT_ERROR, str(err))

    # [1] Planner
    try:
        outline = make_plan(request, columns, llm)
    except CannotAnswerError as err:  # subclass of PlannerError: check first
        return ChainResult(Status.CANNOT_ANSWER, str(err), columns)
    except PlannerError as err:
        return ChainResult(Status.INPUT_ERROR, str(err), columns)
    except LLMError as err:
        return ChainResult(Status.LLM_ERROR, str(err), columns)

    # [2] Coder
    try:
        sql = write_sql(outline, columns, llm)
    except CoderError as err:
        return ChainResult(Status.CODER_ERROR, str(err), columns, outline)
    except LLMError as err:
        return ChainResult(Status.LLM_ERROR, str(err), columns, outline)

    # [3] Reviewer (gate)
    review = review_sql(sql, columns)
    if review.passed:
        return ChainResult(Status.OK, None, columns, outline, sql, review)
    return ChainResult(
        Status.REVIEW_FAILED,
        "The generated SQL failed the review checks",
        columns,
        outline,
        sql,
        review,
    )
