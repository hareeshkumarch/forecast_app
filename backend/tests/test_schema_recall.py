from __future__ import annotations

import polars as pl
import pytest

from app.schema.recall import (
    EXACT,
    RENAMED_TYPES,
    SIMILAR,
    Recall,
    StoredMapping,
    normalise,
    recall,
    similarity,
)
from app.schema.resolve import fingerprint_of, propose

JANUARY = pl.DataFrame(
    {
        "month": ["2026-01-01", "2026-02-01", "2026-03-01"],
        "region": ["North", "North", "North"],
        "units": [10, 12, 14],
    }
)


def _stored(frame: pl.DataFrame, **overrides) -> StoredMapping:
    fields = {
        "fingerprint": fingerprint_of(frame),
        "date_col": "month",
        "target_col": "units",
        "series_keys": ["region"],
        "covariates": [],
        "frequency": None,
        "aggregation": None,
        "columns": {name: str(dtype) for name, dtype in frame.schema.items()},
    }
    fields.update(overrides)
    return StoredMapping(**fields)


def _ask(frame: pl.DataFrame, stored: list[StoredMapping]) -> Recall | None:
    return recall(
        stored,
        fingerprint=fingerprint_of(frame),
        columns={name: str(dtype) for name, dtype in frame.schema.items()},
    )


def test_the_same_file_is_an_exact_match() -> None:
    found = _ask(JANUARY, [_stored(JANUARY)])

    assert found is not None
    assert found.kind == EXACT
    assert found.similarity == 1.0
    assert found.fields["target_col"] == "units"


def test_a_column_that_gained_a_decimal_still_finds_it() -> None:
    february = JANUARY.with_columns(pl.col("units").cast(pl.Float64))

    found = _ask(february, [_stored(JANUARY)])

    assert found is not None
    assert found.kind == RENAMED_TYPES
    assert found.fields["target_col"] == "units"
    assert found.fields["series_keys"] == ["region"]


def test_a_column_the_source_system_added_still_finds_it() -> None:
    wider = JANUARY.with_columns(pl.lit("note").alias("comment"))

    found = _ask(wider, [_stored(JANUARY)])

    assert found is not None
    assert found.kind == SIMILAR
    assert found.fields["date_col"] == "month"


def test_a_column_that_went_away_is_named_rather_than_dropped_in_silence() -> None:
    without_region = JANUARY.drop("region")

    found = _ask(without_region, [_stored(JANUARY)])

    assert found is not None
    assert found.fields["series_keys"] == []
    assert found.missing == ("region",)


def test_a_renamed_column_is_matched_on_its_normalised_name() -> None:
    stored = _stored(JANUARY, target_col="Units", date_col="Month")

    found = _ask(JANUARY, [stored])

    assert found is not None
    assert found.fields["target_col"] == "units"
    assert found.fields["date_col"] == "month"


def test_a_mapping_whose_target_is_gone_is_not_used_at_all() -> None:
    renamed = JANUARY.rename({"units": "quantity"})

    assert _ask(renamed, [_stored(JANUARY)]) is None


def test_an_unrelated_file_finds_nothing() -> None:
    other = pl.DataFrame({"ticket": ["a"], "opened": ["2026-01-01"], "priority": ["high"]})

    assert _ask(other, [_stored(JANUARY)]) is None


def test_the_exact_match_wins_over_a_similar_one() -> None:
    wider = JANUARY.with_columns(pl.lit(1).alias("extra"))
    stored = [_stored(JANUARY), _stored(wider, target_col="extra")]

    found = _ask(JANUARY, stored)

    assert found is not None and found.kind == EXACT
    assert found.fields["target_col"] == "units"


def test_the_closest_of_several_similar_ones_wins() -> None:
    near = JANUARY.with_columns(pl.lit(1).alias("extra"))
    far = pl.DataFrame({"month": ["2026-01-01"], "units": [1], "a": [1], "b": [1], "c": [1]})
    stored = [_stored(far, series_keys=[]), _stored(near)]

    found = _ask(JANUARY, stored)

    assert found is not None
    assert found.fields["series_keys"] == ["region"]


def test_nothing_stored_is_not_an_error() -> None:
    assert _ask(JANUARY, []) is None


class TestSimilarity:
    def test_identical_sets_score_one(self) -> None:
        assert similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_it_is_counted_against_the_union(self) -> None:
        assert similarity({"a", "b"}, {"a", "b", "c", "d"}) == 0.5

    def test_nothing_in_common_scores_zero(self) -> None:
        assert similarity({"a"}, {"b"}) == 0.0

    def test_an_empty_side_scores_zero_rather_than_dividing_by_it(self) -> None:
        assert similarity(set(), {"a"}) == 0.0


class TestNormalise:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Net Revenue (USD)", "net_revenue_usd"),
            ("net_revenue_usd", "net_revenue_usd"),
            ("  Month  ", "month"),
            ("UNITS", "units"),
        ],
    )
    def test_spellings_of_one_column_agree(self, raw: str, expected: str) -> None:
        assert normalise(raw) == expected


class TestThroughTheProposal:
    def test_a_type_change_is_reported_as_a_type_change(self) -> None:
        february = JANUARY.with_columns(pl.col("units").cast(pl.Float64))
        found = _ask(february, [_stored(JANUARY)])
        assert found is not None and found.same_columns

        proposal, _ = propose(february, remembered=found)

        assert proposal.target_col == "units"
        codes = {warning.code for warning in proposal.warnings}
        assert codes == {"remembered_across_a_type_change"}
        assert proposal.confidence == 1.0, "the same columns are the same report"

    def test_a_genuinely_partial_match_asks_to_be_checked(self) -> None:
        wider = JANUARY.with_columns(pl.lit("x").alias("comment"))
        found = _ask(wider, [_stored(JANUARY)])
        assert found is not None and not found.same_columns

        proposal, _ = propose(wider, remembered=found)

        codes = {warning.code for warning in proposal.warnings}
        assert "remembered_from_a_similar_file" in codes

    def test_an_exact_match_is_carried_without_a_caveat(self) -> None:
        found = _ask(JANUARY, [_stored(JANUARY)])
        assert found is not None

        proposal, _ = propose(JANUARY, remembered=found)

        codes = {warning.code for warning in proposal.warnings}
        assert "remembered_from_a_similar_file" not in codes
        assert proposal.confidence == 1.0

    def test_a_near_match_does_not_claim_full_confidence(self) -> None:
        wider = JANUARY.with_columns(pl.lit("x").alias("comment"))
        found = _ask(wider, [_stored(JANUARY)])
        assert found is not None

        proposal, _ = propose(wider, remembered=found)

        assert proposal.confidence < 1.0
