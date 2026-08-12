"""Turning a parsed file plus a column mapping into usable measurements.

The validation here draws a firm line between two kinds of problem, and the
distinction matters more than it looks:

  * **errors** block the upload — a required input is unmapped, or too few
    usable rows remain. Nothing can be fitted.
  * **warnings** never block. In particular, data lying *outside* the project's
    declared range is a warning and must stay one: measurements from a regime
    the project does not yet cover are the single most valuable contribution
    there is, because they are what extends a model's validity domain.
    Rejecting them would defeat the purpose of the platform.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from api.models import Project
from api.services.tabular import ParsedTable


@dataclass
class ColumnSummary:
    variable_key: str
    column: str
    n_present: int
    minimum: float | None
    maximum: float | None


@dataclass
class ValidationReport:
    n_rows_in_file: int = 0
    n_rows_usable: int = 0
    n_rows_dropped: int = 0
    #: {variable_key: [min, max]} over the usable rows — what a contribution
    #: discloses about its inputs, and what grows the published domain.
    feature_ranges: dict[str, list[float]] = field(default_factory=dict)
    columns: list[ColumnSummary] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "n_rows_in_file": self.n_rows_in_file,
            "n_rows_usable": self.n_rows_usable,
            "n_rows_dropped": self.n_rows_dropped,
            "feature_ranges": self.feature_ranges,
            "columns": [
                {
                    "variable_key": c.variable_key,
                    "column": c.column,
                    "n_present": c.n_present,
                    "min": c.minimum,
                    "max": c.maximum,
                }
                for c in self.columns
            ],
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass
class BuiltData:
    """Aligned design matrix and targets, over the rows usable for each."""

    feature_keys: list[str]
    #: Rows of input values, in project input order. Order is contractual.
    X: list[list[float]]
    #: {target_key: y values}, aligned with X row for row.
    y: dict[str, list[float]]
    report: ValidationReport


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def build_and_validate(
    project: Project,
    table: ParsedTable,
    mapping: dict[str, str],
    *,
    min_rows: int,
) -> BuiltData:
    """Assemble X and y from a confirmed mapping, and report on the result.

    `mapping` is {variable_key: column name} covering inputs and targets.
    """
    report = ValidationReport(n_rows_in_file=table.n_rows)

    # Inputs are taken in the project's declared order. A permuted design
    # matrix produces coefficients that are wrong without looking wrong, so
    # this ordering is not a detail.
    inputs = sorted(project.inputs, key=lambda item: item.position)
    targets = sorted(project.targets, key=lambda item: item.position)

    feature_keys = [item.variable.key for item in inputs]
    target_keys = [item.variable.key for item in targets]

    for item in inputs:
        key = item.variable.key
        column = mapping.get(key)
        if not column and item.required:
            report.errors.append(
                f"Required input '{item.variable.display_name}' is not matched "
                f"to any column."
            )
        elif column and column not in table.columns:
            report.errors.append(
                f"Input '{item.variable.display_name}' is mapped to a column "
                f"'{column}' that is not in the file."
            )

    mapped_targets = [key for key in target_keys if mapping.get(key)]
    if not mapped_targets:
        report.errors.append(
            "At least one of the project's target quantities must be matched to "
            "a column — otherwise there is nothing to predict."
        )
    for key in mapped_targets:
        if mapping[key] not in table.columns:
            report.errors.append(f"Target '{key}' is mapped to a column not in the file.")

    used_columns = [mapping[k] for k in mapping if mapping.get(k)]
    duplicated = {c for c in used_columns if used_columns.count(c) > 1}
    if duplicated:
        report.errors.append(
            f"The same column is used for more than one quantity: "
            f"{', '.join(sorted(duplicated))}."
        )

    if report.errors:
        return BuiltData(feature_keys, [], {}, report)

    # Only rows complete in every mapped input *and* every mapped target are
    # usable; a partially filled row cannot contribute to a fit.
    required_columns = [mapping[item.variable.key] for item in inputs if mapping.get(item.variable.key)]
    X: list[list[float]] = []
    y: dict[str, list[float]] = {key: [] for key in mapped_targets}
    seen_rows: set[tuple[float, ...]] = set()
    duplicate_rows = 0

    for row in table.rows:
        features = [_finite(row.get(column)) for column in required_columns]
        outputs = {key: _finite(row.get(mapping[key])) for key in mapped_targets}
        if any(value is None for value in features) or any(
            value is None for value in outputs.values()
        ):
            report.n_rows_dropped += 1
            continue

        signature = tuple(features) + tuple(outputs[key] for key in mapped_targets)
        if signature in seen_rows:
            duplicate_rows += 1
        seen_rows.add(signature)

        X.append([value for value in features if value is not None])
        for key, value in outputs.items():
            if value is not None:
                y[key].append(value)

    report.n_rows_usable = len(X)

    if report.n_rows_dropped:
        report.warnings.append(
            f"{report.n_rows_dropped} row(s) were skipped because a mapped "
            f"column was empty or not a number."
        )
    if duplicate_rows:
        report.warnings.append(
            f"{duplicate_rows} row(s) are exact duplicates of another row. They "
            f"are kept, but repeated measurements weigh twice in the fit — check "
            f"this is intended."
        )

    if report.n_rows_usable < min_rows:
        report.errors.append(
            f"Only {report.n_rows_usable} usable row(s); at least {min_rows} are "
            f"required. This threshold is about privacy rather than statistics: "
            f"the summary sums a contribution can disclose are not anonymous on "
            f"very few rows."
        )
        return BuiltData(feature_keys, X, y, report)

    # Observed coverage, per input and per mapped target.
    for position, item in enumerate(inputs):
        key = item.variable.key
        column = mapping.get(key)
        if not column:
            continue
        values = [row[position] for row in X]
        low, high = min(values), max(values)
        report.feature_ranges[key] = [low, high]
        report.columns.append(
            ColumnSummary(key, column, len(values), low, high)
        )

        # Outside the declared range is a warning, never an error. See the
        # module docstring: this is how a validity domain grows.
        if item.expected_min is not None and low < item.expected_min:
            report.warnings.append(
                f"{item.variable.display_name} goes down to {low:g}, below the "
                f"project's declared minimum of {item.expected_min:g}. That is "
                f"not a problem — it extends the model's domain — but the owner "
                f"should know."
            )
        if item.expected_max is not None and high > item.expected_max:
            report.warnings.append(
                f"{item.variable.display_name} goes up to {high:g}, above the "
                f"project's declared maximum of {item.expected_max:g}. That is "
                f"not a problem — it extends the model's domain — but the owner "
                f"should know."
            )
        if low == high:
            report.warnings.append(
                f"{item.variable.display_name} is constant at {low:g} in this "
                f"file. Its effect cannot be estimated from these rows alone, "
                f"though they still help once pooled with others."
            )

    for key in target_keys:
        column = mapping.get(key)
        if not column:
            report.warnings.append(
                f"Target '{key}' is not present in this file. The other "
                f"target(s) will still be used."
            )
            continue
        values = y[key]
        report.columns.append(
            ColumnSummary(key, column, len(values), min(values), max(values))
        )

    return BuiltData(feature_keys, X, y, report)
