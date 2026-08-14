from __future__ import annotations

import csv
import io
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ValidationError
from app.database.sample_data import generate_csv_bytes
from app.services import dataset_service

UPLOAD = "/api/datasets/upload"


def csv_bytes(header: list[str], rows: list[list[object]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def weekly(count: int, start: date = date(2023, 1, 2)) -> list[date]:
    return [start + timedelta(weeks=index) for index in range(count)]


def send(content: bytes, name: str = "file.csv") -> dict[str, tuple[str, bytes, str]]:
    return {"file": (name, content, "text/csv")}


class TestAFileThatCannotBeForecastIsRefused:
    async def test_a_file_with_no_numbers_never_becomes_a_dataset(
        self, client: AsyncClient
    ) -> None:
        content = csv_bytes(
            ["week", "note"],
            [[day.isoformat(), f"comment {index}"] for index, day in enumerate(weekly(30))],
        )

        response = await client.post(UPLOAD, files=send(content))

        assert response.status_code == 422
        error = response.json()["error"]
        assert "numbers" in error["message"]
        assert error["detail"]["intake"]["verdict"] == "refuse"
        assert error["detail"]["intake"]["refusals"]

    async def test_a_refused_upload_leaves_no_dataset_and_no_file(
        self, client: AsyncClient
    ) -> None:
        before = sorted(settings.uploads_dir.glob("*")) if settings.uploads_dir.exists() else []
        listed = (await client.get("/api/datasets?limit=200")).json()["total"]

        content = csv_bytes(
            ["week", "note"],
            [[day.isoformat(), "text"] for day in weekly(30)],
        )
        assert (await client.post(UPLOAD, files=send(content))).status_code == 422

        after = sorted(settings.uploads_dir.glob("*")) if settings.uploads_dir.exists() else []
        assert after == before, "a refused upload is not left on disk"
        assert (await client.get("/api/datasets?limit=200")).json()["total"] == listed

    async def test_the_refusal_travels_through_the_service_too(self, session: AsyncSession) -> None:
        content = csv_bytes(["week"], [[day.isoformat()] for day in weekly(30)])

        with pytest.raises(ValidationError) as raised:
            await dataset_service.create_from_upload(session, content, "one-column.csv")

        assert raised.value.detail["intake"]["verdict"] == "refuse"


class TestAFileThatNeedsAnAnswerAsksForOne:
    async def test_duplicate_rows_are_asked_about_and_never_silently_summed(
        self, client: AsyncClient
    ) -> None:
        rows: list[list[object]] = []
        for day in weekly(30):
            rows.append([day.isoformat(), 100.0])
            rows.append([day.isoformat(), 140.0])
        content = csv_bytes(["week", "units"], rows)

        payload = (await client.post(UPLOAD, files=send(content))).json()

        assert payload["needs_confirmation"] is True
        assert "duplicate_keys" in {question["code"] for question in payload["questions"]}
        asked = next(q for q in payload["questions"] if q["code"] == "duplicate_keys")
        assert asked["options"]
        assert asked["evidence"], "the rows it means are named"

    async def test_the_question_survives_a_reload_of_the_dataset(self, client: AsyncClient) -> None:
        rows: list[list[object]] = []
        for day in weekly(30):
            rows.append([day.isoformat(), 100.0])
            rows.append([day.isoformat(), 140.0])

        upload = (await client.post(UPLOAD, files=send(csv_bytes(["week", "units"], rows)))).json()
        dataset_id = upload["dataset"]["id"]

        stored = (await client.get(f"/api/datasets/{dataset_id}")).json()

        assert stored["intake"]["verdict"] == "confirm"
        assert {q["code"] for q in stored["intake"]["questions"]} == {
            q["code"] for q in upload["questions"]
        }


class TestAFileThatIsFineIsNotObstructed:
    async def test_the_sample_panel_uploads_with_nothing_to_answer(
        self, client: AsyncClient
    ) -> None:
        payload = (await client.post(UPLOAD, files=send(generate_csv_bytes(), "sample.csv"))).json()

        assert payload["needs_confirmation"] is False
        assert payload["questions"] == []
        assert payload["dataset"]["intake"]["verdict"] == "proceed"
        assert payload["ready_to_forecast"] is True

    async def test_the_chosen_columns_are_reported_with_their_runner_up(
        self, client: AsyncClient
    ) -> None:
        payload = (await client.post(UPLOAD, files=send(generate_csv_bytes(), "sample.csv"))).json()

        choices = {row["role"]: row for row in payload["dataset"]["intake"]["columns"]}

        assert choices["time"]["chosen"] == "order_date"
        assert choices["target"]["chosen"] == "revenue"
        assert choices["target"]["runner_up"] is not None
        assert choices["target"]["confident"] is True


class TestShortSeriesAreNamedNotHidden:
    async def test_the_list_is_capped_but_the_count_is_not(self, client: AsyncClient) -> None:
        rows: list[list[object]] = []
        for index in range(dataset_service.GATED_SERIES_SHOWN + 10):
            for day in weekly(3):
                rows.append([day.isoformat(), f"sku-{index}", 10.0 + index])
        content = csv_bytes(["week", "sku", "units"], rows)

        intake = (await client.post(UPLOAD, files=send(content))).json()["dataset"]["intake"]

        assert intake["gated_series_count"] > dataset_service.GATED_SERIES_SHOWN
        assert len(intake["gated_series"]) == dataset_service.GATED_SERIES_SHOWN
        assert all(gate["observations"] < gate["required"] for gate in intake["gated_series"])
