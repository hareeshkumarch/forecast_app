from __future__ import annotations

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Self  # noqa: UP035

from app.core.errors import ValidationError
from app.datasets.queries import MISSING_KEY
from app.models.enums import ForecastFrequency, MeasureAggregation
from app.schema.contract import (
    CANONICAL_COLUMNS,
    DS,
    SERIES_ID,
    SERIES_KEY_SEPARATOR,
    SINGLE_SERIES_ID,
    MappingProposal,
    Y,
)

TRUNCATE_EVERY: dict[ForecastFrequency, str] = {
    ForecastFrequency.DAILY: "1d",
    ForecastFrequency.WEEKLY: "1w",
    ForecastFrequency.MONTHLY: "1mo",
    ForecastFrequency.QUARTERLY: "1q",
}

assert set(TRUNCATE_EVERY) == set(ForecastFrequency), "every frequency needs a truncation window"

REDUCERS = {
    MeasureAggregation.SUM: lambda column: column.sum(),
    MeasureAggregation.MEAN: lambda column: column.mean(),
    MeasureAggregation.MEDIAN: lambda column: column.median(),
    MeasureAggregation.LAST: lambda column: column.last(),
    MeasureAggregation.MIN: lambda column: column.min(),
    MeasureAggregation.MAX: lambda column: column.max(),
}


class CanonicalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    date_col: str = Field(min_length=1)
    target_col: str = Field(min_length=1)
    series_keys: list[str] = Field(default_factory=list)
    covariates: list[str] = Field(default_factory=list)
    frequency: ForecastFrequency = ForecastFrequency.MONTHLY
    aggregation: MeasureAggregation = MeasureAggregation.SUM

    @model_validator(mode="after")
    def _columns_are_distinct(self) -> Self:
        if self.date_col == self.target_col:
            raise ValueError("The date column and the target column must be different columns.")
        overlap = ({self.date_col, self.target_col} | set(self.series_keys)) & set(self.covariates)
        if overlap:
            raise ValueError(f"{sorted(overlap)} cannot be a covariate and a key at once.")
        return self

    @classmethod
    def from_proposal(cls, proposal: MappingProposal) -> CanonicalConfig:
        if not proposal.complete:
            raise ValidationError(
                "This mapping has no date column or no target column, so no canonical frame "
                "can be built from it.",
                detail={"code": "incomplete_mapping", "mapping": proposal.as_dict()},
            )
        return cls(
            date_col=str(proposal.date_col),
            target_col=str(proposal.target_col),
            series_keys=list(proposal.series_keys),
            covariates=list(proposal.covariates),
            frequency=proposal.frequency or ForecastFrequency.MONTHLY,
            aggregation=proposal.aggregation or MeasureAggregation.SUM,
        )


def to_canonical(frame: pl.DataFrame, config: CanonicalConfig) -> pl.DataFrame:
    missing = [
        name
        for name in (config.date_col, config.target_col, *config.series_keys, *config.covariates)
        if name not in frame.columns
    ]
    if missing:
        raise ValidationError(
            f"The mapping names column(s) this file does not have: {', '.join(missing)}.",
            detail={"code": "unknown_column", "columns": missing},
        )

    keys = [
        pl.col(name).cast(pl.Utf8, strict=False).fill_null(MISSING_KEY)
        for name in config.series_keys
    ]
    identity = (
        pl.concat_str(keys, separator=SERIES_KEY_SEPARATOR)
        if keys
        else pl.lit(SINGLE_SERIES_ID, dtype=pl.Utf8)
    )

    prepared = (
        frame.select(
            identity.alias(SERIES_ID),
            pl.col(config.date_col).cast(pl.Date, strict=False).alias(DS),
            pl.col(config.target_col).cast(pl.Float64, strict=False).alias(Y),
            *[pl.col(name).cast(pl.Float64, strict=False) for name in config.covariates],
        )
        .drop_nulls(subset=[DS, Y])
        .with_columns(pl.col(DS).dt.truncate(TRUNCATE_EVERY[config.frequency]))
        .sort([SERIES_ID, DS])
    )

    reduce = REDUCERS[config.aggregation]
    canonical = (
        prepared.group_by([SERIES_ID, DS], maintain_order=True)
        .agg(
            reduce(pl.col(Y)),
            *[pl.col(name).mean() for name in config.covariates],
        )
        .sort([SERIES_ID, DS])
    )

    assert_canonical(canonical, covariates=config.covariates)
    return canonical


def assert_canonical(frame: pl.DataFrame, *, covariates: list[str] | None = None) -> None:
    # The class, not an instance: `pl.Float64` rather than `pl.Float64()`.
    # Polars compares the two forms as equal, which is all this dict is for.
    expected: dict[str, type[pl.DataType]] = {
        SERIES_ID: pl.Utf8,
        DS: pl.Date,
        Y: pl.Float64,
        **dict.fromkeys(covariates or [], pl.Float64),
    }

    for column, dtype in expected.items():
        if column not in frame.columns:
            raise ValidationError(
                f"The canonical frame is missing its '{column}' column.",
                detail={"code": "canonical_column_missing", "column": column},
            )
        if frame.schema[column] != dtype:
            raise ValidationError(
                f"'{column}' is {frame.schema[column]} in the canonical frame, not {dtype}.",
                detail={
                    "code": "canonical_dtype_mismatch",
                    "column": column,
                    "expected": str(dtype),
                    "actual": str(frame.schema[column]),
                },
            )

    unexpected = [name for name in frame.columns if name not in expected]
    if unexpected:
        raise ValidationError(
            f"The canonical frame carries column(s) nothing declared: {', '.join(unexpected)}.",
            detail={"code": "canonical_column_unexpected", "columns": unexpected},
        )

    if frame.select(CANONICAL_COLUMNS[:2]).is_duplicated().any():
        raise ValidationError(
            "The canonical frame holds more than one row for a series and period.",
            detail={"code": "canonical_duplicate_grain"},
        )
