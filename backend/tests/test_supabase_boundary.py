"""
Tests for the Supabase response boundary (Phase 13 follow-up).

These defend a specific dependency defect. postgrest-py parses a
response with pydantic's recursive JSON validator and, when that
raises, returns the raw JSON *text* as `data` while the type still
claims rows. Two live failures came from it:

  - GET /api/v1/campus/{code}/twin returned 500, because an
    incident row arrived as a `str` and could not be unpacked
    into a model;
  - incident de-duplication raised `'str' object has no attribute
    'get'` on every reading, so the same incident was re-raised.

The repair lives at the boundary, so these tests are about the
boundary rather than about those two symptoms.
"""

import json

import pytest

from app.db.supabase import (
    _Query,
    _TableBuilder,
    _parse_if_text,
)


class FakeResponse:
    """A stand-in for postgrest's APIResponse."""

    def __init__(self, data):
        self.data = data

    def __repr__(self):
        return f"FakeResponse(data={self.data!r})"


# ============================================================
# PARSING THE FALLBACK
# ============================================================


class TestParseIfText:
    def test_parses_rows_the_dependency_left_as_text(self):
        rows = [
            {"id": "a", "evidence": [{"rule": "overheating"}]},
            {"id": "b", "evidence": []},
        ]

        response = _parse_if_text(
            FakeResponse(json.dumps(rows))
        )

        assert response.data == rows
        assert isinstance(response.data, list)

    def test_leaves_a_parsed_list_alone(self):
        rows = [{"id": "a"}]

        response = _parse_if_text(FakeResponse(rows))

        assert response.data is rows

    def test_leaves_an_empty_response_alone(self):
        # postgrest uses [] rather than "" when there is no
        # fallback to take, and that must not be re-parsed.
        response = _parse_if_text(FakeResponse([]))

        assert response.data == []

    def test_handles_a_deeply_nested_payload(self):
        """
        The shape that broke the dependency's parser: nesting
        deep enough to exhaust a recursive JSON reader.
        """

        nested = {"value": None}

        for _ in range(400):
            nested = {"value": nested}

        response = _parse_if_text(
            FakeResponse(json.dumps([{"evidence": nested}]))
        )

        assert isinstance(response.data, list)
        assert response.data[0]["evidence"] == nested

    def test_rejects_a_body_that_is_neither_rows_nor_json(self):
        """
        Failing at the boundary is the point. Letting a string
        travel on as though it were rows is what made the
        original bug so hard to place.
        """

        with pytest.raises(TypeError):
            _parse_if_text(FakeResponse("not json at all"))

    def test_a_missing_data_attribute_is_not_an_error(self):
        class Empty:
            pass

        assert isinstance(_parse_if_text(Empty()), Empty)


# ============================================================
# THE FLUENT CHAIN
# ============================================================


class FakeBuilder:
    """Mimics a postgrest query builder: fluent, then terminal."""

    def __init__(self, response):
        self._response = response
        self.calls = []

    def select(self, *args, **kwargs):
        self.calls.append(("select", args))
        return self

    def eq(self, *args, **kwargs):
        self.calls.append(("eq", args))
        return self

    def order(self, *args, **kwargs):
        self.calls.append(("order", args))
        return self

    def limit(self, *args, **kwargs):
        self.calls.append(("limit", args))
        return self

    def execute(self):
        return self._response


class TestQuery:
    def test_repairs_at_the_end_of_a_chain(self):
        rows = [{"id": "a"}]

        builder = FakeBuilder(
            FakeResponse(json.dumps(rows))
        )

        result = (
            _Query(builder)
            .select("*")
            .eq("campus_id", "x")
            .order("impact_score", desc=True)
            .limit(10)
            .execute()
        )

        assert result.data == rows

    def test_keeps_wrapping_every_intermediate_step(self):
        """
        The chain is three calls deep here. If any intermediate
        call returned an unwrapped builder, the repair would be
        skipped and the bug would come back at a call site that
        looks correct.
        """

        builder = FakeBuilder(
            FakeResponse(json.dumps([{"id": "a"}]))
        )

        query = _Query(builder).select("*")

        assert isinstance(query, _Query)
        assert isinstance(query.eq("id", "a"), _Query)
        assert isinstance(
            query.eq("id", "a").limit(1), _Query
        )

    def test_passes_arguments_through_unchanged(self):
        builder = FakeBuilder(FakeResponse([]))

        (
            _Query(builder)
            .select("id,evidence")
            .eq("status", "open")
            .order("detected_at", desc=True)
            .limit(20)
            .execute()
        )

        assert builder.calls == [
            ("select", ("id,evidence",)),
            ("eq", ("status", "open")),
            ("order", ("detected_at",)),
            ("limit", (20,)),
        ]

    def test_non_callable_attributes_are_exposed(self):
        builder = FakeBuilder(FakeResponse([]))
        builder.some_attribute = "value"

        assert _Query(builder).some_attribute == "value"


# ============================================================
# THE CLIENT SURFACE
# ============================================================


class FakeClient:
    def __init__(self):
        self.table_calls = []
        self.auth = "auth-handle"

    def table(self, name):
        self.table_calls.append(name)
        return FakeBuilder(
            FakeResponse(json.dumps([{"table": name}]))
        )


class TestTableBuilder:
    def test_table_returns_a_repairing_query(self):
        client = FakeClient()

        query = _TableBuilder(client).table("incidents")

        assert isinstance(query, _Query)
        assert query.execute().data == [{"table": "incidents"}]

    def test_anything_else_is_delegated_untouched(self):
        # Nothing outside `.table()` is used by this project, so
        # nothing outside it is wrapped.
        client = FakeClient()

        assert _TableBuilder(client).auth == "auth-handle"
