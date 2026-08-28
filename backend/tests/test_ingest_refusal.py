from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from app.datasets.profiler import profile_frame
from app.datasets.refusal import (
    MIN_TARGET_CONFIDENCE,
    Verdict,
    assess,
    duplicate_keys,
    history_gate,
    series_lengths_from,
)
from app.models.enums import ForecastFrequency


def weekly(count: int, start: date = date(2023, 1, 2)) -> list[date]:
    return [start + timedelta(weeks=index) for index in range(count)]


def judge(frame: pl.DataFrame, **kwargs: object) -> object:
    return assess(profile_frame(frame), frame=frame, **kwargs)  # type: ignore[arg-type]


def codes(verdict: object) -> set[str]:
    return {question.code for question in verdict.questions}  # type: ignore[attr-defined]


class TestFilesThatAreRefused:
    def test_a_single_column_file_is_refused_with_a_reason(self) -> None:
        frame = pl.DataFrame({"week": weekly(40)})

        verdict = judge(frame)

        assert verdict.verdict is Verdict.REFUSE
        assert any("at least a column of dates" in r or "numbers" in r for r in verdict.refusals)

    def test_a_file_with_no_readable_dates_is_refused(self) -> None:
        frame = pl.DataFrame(
            {"reference": [f"ORD-{i:05d}" for i in range(40)], "units": list(range(40))}
        )

        verdict = judge(frame)

        assert verdict.verdict is Verdict.REFUSE
        assert any("reads as dates" in r for r in verdict.refusals)

    def test_a_file_with_no_numbers_to_forecast_is_refused(self) -> None:
        frame = pl.DataFrame({"week": weekly(30), "note": ["ok"] * 30})

        verdict = judge(frame)

        assert verdict.verdict is Verdict.REFUSE
        assert any("numbers to forecast" in r for r in verdict.refusals)

    def test_a_header_with_no_rows_under_it_is_refused(self) -> None:
        frame = pl.DataFrame({"week": [], "units": []}, schema={"week": pl.Date, "units": pl.Int64})

        verdict = judge(frame)

        assert verdict.verdict is Verdict.REFUSE

    def test_a_refusal_never_carries_a_column_choice_forward(self) -> None:
        verdict = judge(pl.DataFrame({"week": weekly(40)}))

        assert verdict.verdict is Verdict.REFUSE
        assert verdict.questions == []


class TestFilesThatAreQueried:
    def test_uk_dates_that_could_be_either_are_asked_about_with_examples(self) -> None:
        frame = pl.DataFrame(
            {
                "date": [f"{d:02d}/0{m}/2024" for m in (1, 2, 3) for d in (3, 5, 7, 9, 11)],
                "units": list(range(15)),
            }
        )

        verdict = judge(frame)

        assert verdict.verdict is Verdict.CONFIRM
        assert "ambiguous_date_order" in codes(verdict)
        question = next(q for q in verdict.questions if q.code == "ambiguous_date_order")
        assert question.evidence, "asked about the order without showing a single row"
        assert len(question.options) == 2

    def test_unambiguous_uk_dates_are_read_without_asking(self) -> None:
        frame = pl.DataFrame(
            {
                "date": [f"{d}/03/2024" for d in (13, 14, 15, 16, 17, 18, 19, 20)],
                "units": [10, 12, 9, 14, 11, 13, 8, 15],
            }
        )

        verdict = judge(frame)

        assert "ambiguous_date_order" not in codes(verdict)

    def test_duplicate_keys_are_counted_and_asked_about_never_deduplicated(self) -> None:
        periods = weekly(20)
        frame = pl.DataFrame(
            {"week": periods + periods, "units": list(range(20)) + list(range(100, 120))}
        )

        verdict = judge(frame)

        assert verdict.verdict is Verdict.CONFIRM
        assert "duplicate_keys" in codes(verdict)
        question = next(q for q in verdict.questions if q.code == "duplicate_keys")
        assert "20 row(s)" in question.question
        assert question.evidence
        assert not any("last" in option for option in question.options)

    def test_two_equally_good_target_columns_are_a_question_not_a_coin_toss(self) -> None:
        frame = pl.DataFrame(
            {
                "week": weekly(40),
                "net_revenue": [100 + i for i in range(40)],
                "gross_revenue": [120 + i for i in range(40)],
            }
        )

        verdict = judge(frame)

        target = next(c for c in verdict.choices if c.role == "target")
        if not target.confident:
            assert "low_confidence_target" in codes(verdict)
            assert target.runner_up is not None

    def test_the_runner_up_is_always_reported_even_when_confident(self) -> None:
        frame = pl.DataFrame(
            {"week": weekly(40), "units_sold": list(range(40)), "line_no": list(range(40))}
        )

        verdict = judge(frame)
        target = next(c for c in verdict.choices if c.role == "target")

        assert target.chosen is not None
        assert target.runner_up is not None
        assert target.confidence >= target.runner_up_confidence

    def test_irregular_spacing_is_reported_rather_than_resampled(self) -> None:
        scattered = [date(2024, 1, 1), date(2024, 1, 3), date(2024, 2, 17), date(2024, 5, 2)]
        frame = pl.DataFrame({"date": scattered * 4, "units": list(range(16))})

        verdict = judge(frame)

        if profile_frame(frame).detected_frequency is None:
            assert "irregular_spacing" in codes(verdict)


class TestFilesThatRunButAreReportedOn:
    def test_an_excel_serial_column_is_read_as_dates(self) -> None:
        frame = pl.DataFrame(
            {"order_date": [45292 + 7 * i for i in range(30)], "units": list(range(30))}
        )

        result = profile_frame(frame)
        verdict = assess(result, frame=frame)

        assert verdict.verdict is not Verdict.REFUSE
        chosen = next(c for c in verdict.choices if c.role == "time")
        assert chosen.chosen == "order_date"

    def test_an_all_zero_series_is_not_mistaken_for_an_empty_one(self) -> None:
        frame = pl.DataFrame({"week": weekly(60), "units": [0] * 60})

        verdict = judge(frame)

        assert verdict.verdict is not Verdict.REFUSE
        target = next(c for c in verdict.choices if c.role == "target")
        assert target.chosen == "units"

    def test_negative_quantities_are_kept_not_clipped(self) -> None:
        values = [10, -4, 12, -2, 8] * 8
        frame = pl.DataFrame({"week": weekly(40), "units": values})

        verdict = judge(frame)

        assert verdict.verdict is not Verdict.REFUSE
        assert verdict.rows_quarantined == 0

    def test_three_weeks_of_history_names_the_series_and_what_it_needed(self) -> None:
        gates = history_gate({"Chilled": 3, "Ambient": 260}, ForecastFrequency.WEEKLY)

        assert [gate.label for gate in gates] == ["Chilled"]
        gate = gates[0]
        assert gate.observations == 3
        assert gate.required > 3
        assert "baseline" in gate.reason
        assert str(gate.required) in gate.reason

    def test_every_short_series_is_named_individually(self) -> None:
        lengths = {"A": 2, "B": 3, "C": 500, "D": 1}

        gates = history_gate(lengths, ForecastFrequency.WEEKLY)

        assert {gate.label for gate in gates} == {"A", "B", "D"}
        assert all(gate.as_dict()["reason"] for gate in gates)


class TestMixedDateFormatsWithinOneColumn:
    def test_a_column_that_mostly_agrees_is_read_and_the_rest_quarantined(self) -> None:
        good = [f"2024-{m:02d}-01" for m in range(1, 13)] * 3
        rubbish = ["not a date", "", "13th of never"]
        frame = pl.DataFrame({"date": good + rubbish, "units": list(range(len(good) + 3))})

        result = profile_frame(frame)
        verdict = assess(result, frame=frame)

        assert verdict.verdict is not Verdict.REFUSE
        held = [q for q in verdict.quarantined if q.code == "unreadable_values"]
        if held:
            assert held[0].count > 0
            assert held[0].reason

    def test_a_column_that_agrees_on_nothing_is_not_read_as_a_date(self) -> None:
        chaos = ["2024-01-01", "15/03/2024", "March 2024", "45292", "Q1", "", "n/a", "later"]
        frame = pl.DataFrame({"date": chaos * 3, "units": list(range(24))})

        verdict = judge(frame)

        assert verdict.verdict is Verdict.REFUSE or "low_confidence_time" in codes(verdict)


class TestNothingIsEverSilent:
    @pytest.mark.parametrize(
        "frame",
        [
            pl.DataFrame({"week": weekly(40)}),
            pl.DataFrame({"reference": [f"X{i}" for i in range(20)], "units": list(range(20))}),
            pl.DataFrame(
                {"week": weekly(20) + weekly(20), "units": list(range(40))},
            ),
            pl.DataFrame({"week": weekly(30), "note": ["ok"] * 30}),
        ],
    )
    def test_every_broken_file_produces_a_specific_message(self, frame: pl.DataFrame) -> None:
        verdict = judge(frame)

        assert verdict.verdict is not Verdict.PROCEED
        messages = list(verdict.refusals) + [q.question for q in verdict.questions]
        assert messages, "a file that cannot be forecast produced no message at all"
        for message in messages:
            assert len(message) > 30, f"message is not actionable: {message!r}"

    def test_a_clean_file_is_allowed_straight_through(self) -> None:
        frame = pl.DataFrame(
            {
                "week_ending": weekly(120),
                "units_sold": [100 + (i % 7) * 3 for i in range(120)],
            }
        )

        verdict = judge(frame)

        assert (
            verdict.verdict is Verdict.PROCEED
        ), f"a clean file was queried: {[q.question for q in verdict.questions]}"
        assert verdict.refusals == []
        assert verdict.rows_quarantined == 0

    def test_the_whole_verdict_survives_a_round_trip_to_json(self) -> None:
        import json

        frame = pl.DataFrame({"week": weekly(20) + weekly(20), "units": list(range(40))})

        payload = json.loads(json.dumps(judge(frame).as_dict()))

        assert payload["verdict"] == "confirm"
        assert isinstance(payload["columns"], list)
        assert isinstance(payload["questions"], list)


class TestHelpers:
    def test_duplicate_keys_counts_extra_rows_not_groups(self) -> None:
        frame = pl.DataFrame({"week": [date(2024, 1, 1)] * 3, "units": [1, 2, 3]})

        repeated, examples = duplicate_keys(frame, "week")

        assert repeated == 2
        assert examples

    def test_duplicate_keys_respects_the_series_grain(self) -> None:
        frame = pl.DataFrame(
            {
                "week": [date(2024, 1, 1)] * 2,
                "region": ["North", "South"],
                "units": [1, 2],
            }
        )

        assert duplicate_keys(frame, "week", ["region"])[0] == 0
        assert duplicate_keys(frame, "week")[0] == 1

    def test_series_lengths_counts_distinct_periods_per_group(self) -> None:
        frame = pl.DataFrame(
            {
                "week": weekly(5) + weekly(3),
                "region": ["North"] * 5 + ["South"] * 3,
                "units": list(range(8)),
            }
        )

        assert series_lengths_from(frame, "week", ["region"]) == {"North": 5, "South": 3}

    def test_without_a_grain_the_whole_file_is_one_series(self) -> None:
        frame = pl.DataFrame({"week": weekly(9), "units": list(range(9))})

        assert series_lengths_from(frame, "week") == {"the total": 9}

    def test_confidence_floor_is_what_the_choice_is_judged_against(self) -> None:
        frame = pl.DataFrame({"week": weekly(60), "units_sold": list(range(60))})

        target = next(c for c in judge(frame).choices if c.role == "target")

        assert target.confident is (target.confidence >= MIN_TARGET_CONFIDENCE)
