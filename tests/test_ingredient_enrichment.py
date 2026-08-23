"""Response parsing and normalisation for pantry enrichment.

No network calls — these cover the layer between a model response and a
database write, which is where invented or malformed numbers have to be
caught. `enrich_batch` itself (the network call) is not covered here.
"""

import pytest

from backend import ingredient_enrichment as enrichment
from backend.ingredient_enrichment import (
    MAX_PLAUSIBLE_COST_PER_KG_CENTS,
    derive_energy_kj,
    match_results,
    normalise_result,
    parse_json_response,
)


class TestParseJsonResponse:
    def test_plain_array(self):
        assert parse_json_response('[{"name": "rice"}]') == [{"name": "rice"}]

    def test_strips_a_markdown_fence(self):
        assert parse_json_response('```json\n[{"name": "rice"}]\n```') == [{"name": "rice"}]

    def test_recovers_an_array_surrounded_by_prose(self):
        text = 'Here you go:\n[{"name": "rice"}]\nLet me know if you need more.'
        assert parse_json_response(text) == [{"name": "rice"}]

    def test_no_array_raises(self):
        with pytest.raises(ValueError):
            parse_json_response("I could not determine that.")


class TestDeriveEnergyKj:
    def test_standard_factor(self):
        # The one figure Claude is not asked to compute itself — see the
        # module docstring on why kJ is derived, not requested.
        assert derive_energy_kj(100) == pytest.approx(418.4, abs=0.5)

    def test_none_stays_none(self):
        assert derive_energy_kj(None) is None

    def test_zero_is_a_real_value_not_missing(self):
        assert derive_energy_kj(0) == 0


class TestNormaliseResult:
    def test_a_confident_whole_food(self):
        raw = {
            "name": "plain flour", "is_human_food": True, "confidence": "high",
            "calories_kcal": 364, "protein_g": 10.3, "fat_g": 1.0,
            "saturated_fat_g": 0.2, "carbs_g": 76.3, "sugars_g": 0.3,
            "fibre_g": 2.7, "sodium_mg": 2, "cost_per_kg_cents": 200,
            "package_size_grams": 1000, "note": None,
        }
        result = normalise_result(raw, requested_name="plain flour")
        assert result["is_human_food"] is True
        assert result["nutrition"]["calories_kcal"] == 364
        assert result["nutrition"]["energy_kj"] == pytest.approx(1523, abs=2)
        assert result["cost_per_kg_cents"] == 200
        assert result["package_size_grams"] == 1000

    def test_not_human_food_carries_nothing_else(self):
        raw = {
            "name": "cat mince", "is_human_food": False,
            "note": "pet food, not for human consumption",
            "calories_kcal": 250,  # a well-behaved model wouldn't send this, but don't trust it
        }
        result = normalise_result(raw, requested_name="cat mince")
        assert result["is_human_food"] is False
        assert result["nutrition"] == {}
        assert result["cost_per_kg_cents"] is None
        assert "pet food" in result["note"]

    @pytest.mark.parametrize(
        "field,value", [("calories_kcal", 5000), ("protein_g", -5), ("sodium_mg", 100_000)]
    )
    def test_implausible_values_become_none(self, field, value):
        raw = {"is_human_food": True, field: value}
        result = normalise_result(raw, requested_name="x")
        assert result["nutrition"][field] is None

    def test_a_saner_field_survives_alongside_a_bad_one(self):
        # One implausible number must not void the whole response.
        raw = {"is_human_food": True, "protein_g": -5, "carbs_g": 20}
        result = normalise_result(raw, requested_name="x")
        assert result["nutrition"]["protein_g"] is None
        assert result["nutrition"]["carbs_g"] == 20

    def test_an_implausible_cost_is_dropped(self):
        raw = {"is_human_food": True, "cost_per_kg_cents": MAX_PLAUSIBLE_COST_PER_KG_CENTS * 5}
        assert normalise_result(raw, requested_name="x")["cost_per_kg_cents"] is None

    def test_a_zero_or_negative_cost_is_dropped(self):
        assert normalise_result({"is_human_food": True, "cost_per_kg_cents": 0}, requested_name="x")["cost_per_kg_cents"] is None
        assert normalise_result({"is_human_food": True, "cost_per_kg_cents": -50}, requested_name="x")["cost_per_kg_cents"] is None

    def test_a_believable_high_value_item_survives(self):
        # Saffron-tier pricing is real; only absurd values should be dropped.
        raw = {"is_human_food": True, "cost_per_kg_cents": 25_000}
        assert normalise_result(raw, requested_name="x")["cost_per_kg_cents"] == 25_000

    def test_malformed_numbers_do_not_raise(self):
        raw = {"is_human_food": True, "protein_g": "unknown", "cost_per_kg_cents": "n/a"}
        result = normalise_result(raw, requested_name="x")
        assert result["nutrition"]["protein_g"] is None
        assert result["cost_per_kg_cents"] is None

    def test_confidence_defaults_and_is_validated(self):
        assert normalise_result({"is_human_food": True}, requested_name="x")["confidence"] == "medium"
        assert normalise_result(
            {"is_human_food": True, "confidence": "extremely sure"}, requested_name="x"
        )["confidence"] == "medium"
        assert normalise_result(
            {"is_human_food": True, "confidence": "LOW"}, requested_name="x"
        )["confidence"] == "low"

    def test_package_size_must_be_positive(self):
        raw = {"is_human_food": True, "package_size_grams": -200}
        assert normalise_result(raw, requested_name="x")["package_size_grams"] is None


class TestMatchResults:
    def test_matches_by_echoed_name(self):
        raw = [{"name": "Banana", "is_human_food": True}, {"name": "Apple", "is_human_food": True}]
        matched = match_results(["apple", "banana"], raw)
        assert set(matched) == {"apple", "banana"}
        assert matched["apple"]["name"] == "apple"

    def test_falls_back_to_position_when_a_name_does_not_echo_back(self):
        # A model that drops the `name` field shouldn't lose the whole batch.
        raw = [{"is_human_food": True}, {"is_human_food": True}]
        matched = match_results(["rice", "flour"], raw)
        assert set(matched) == {"rice", "flour"}

    def test_a_short_response_matches_what_it_can(self):
        raw = [{"name": "rice", "is_human_food": True}]
        matched = match_results(["rice", "flour", "sugar"], raw)
        assert set(matched) == {"rice"}
        assert "flour" not in matched and "sugar" not in matched

    def test_an_empty_response_matches_nothing(self):
        assert match_results(["rice", "flour"], []) == {}

    def test_is_case_and_whitespace_insensitive(self):
        raw = [{"name": "  Plain Flour  ", "is_human_food": True}]
        matched = match_results(["plain flour"], raw)
        assert "plain flour" in matched


class TestTruncatedResponses:
    """A response cut off by max_tokens used to lose the whole batch.

    The real failure looked like this: twenty items requested, the model
    fenced its output and ran out of room partway through item eighteen, so
    there was no closing bracket, `json.loads` failed, `rfind("]")` found
    nothing, and all twenty were reported as "no JSON array in model
    response" — having already been paid for.
    """

    def test_salvages_the_complete_items_from_a_truncated_array(self):
        text = (
            '```json\n[\n'
            '  {"name": "boiling water", "calories_kcal": 0},\n'
            '  {"name": "orange rind", "calories_kcal": 47},\n'
            '  {"name": "light cream cheese", "calories_kcal": 20'
        )
        results = enrichment.parse_json_response(text)
        assert [r["name"] for r in results] == ["boiling water", "orange rind"]

    def test_a_complete_fenced_response_still_parses_whole(self):
        text = '```json\n[{"name": "salt", "sodium_mg": 38758}]\n```'
        assert enrichment.parse_json_response(text) == [
            {"name": "salt", "sodium_mg": 38758}
        ]

    def test_genuine_rubbish_still_raises(self):
        with pytest.raises(ValueError, match="no JSON array"):
            enrichment.parse_json_response("I'm sorry, I can't help with that.")

    def test_salvage_ignores_a_trailing_partial_object(self):
        assert enrichment.salvage_objects('[{"a": 1}, {"b":') == [{"a": 1}]

    def test_salvage_of_an_untruncated_array_returns_everything(self):
        assert enrichment.salvage_objects('[{"a": 1}, {"b": 2}]') == [
            {"a": 1},
            {"b": 2},
        ]


class TestBatchRetry:
    """`enrich_names` turns the two batch-level failure modes into retries."""

    def _result(self, name):
        return {"name": name, "is_human_food": True, "calories_kcal": 1}

    def test_a_truncated_batch_retries_only_the_missing_items(self, monkeypatch):
        calls = []

        def fake_enrich_batch(names):
            calls.append(list(names))
            # First call answers only the first two of four — a truncation.
            if len(calls) == 1:
                return {n: self._result(n) for n in names[:2]}
            return {n: self._result(n) for n in names}

        monkeypatch.setattr(enrichment, "enrich_batch", fake_enrich_batch)
        results = enrichment.enrich_names(["a", "b", "c", "d"])

        assert sorted(results) == ["a", "b", "c", "d"]
        assert calls == [["a", "b", "c", "d"], ["c", "d"]]

    def test_a_failing_batch_is_split_rather_than_lost(self, monkeypatch):
        def fake_enrich_batch(names):
            if len(names) > 1:
                raise RuntimeError("overloaded")
            return {names[0]: self._result(names[0])}

        monkeypatch.setattr(enrichment, "enrich_batch", fake_enrich_batch)
        results = enrichment.enrich_names(["a", "b", "c", "d"])
        assert sorted(results) == ["a", "b", "c", "d"]

    def test_one_hopeless_item_does_not_take_the_batch_with_it(self, monkeypatch):
        def fake_enrich_batch(names):
            if "bad" in names:
                raise RuntimeError("nope")
            return {n: self._result(n) for n in names}

        monkeypatch.setattr(enrichment, "enrich_batch", fake_enrich_batch)
        results = enrichment.enrich_names(["good1", "bad", "good2"])
        assert "bad" not in results
        assert sorted(results) == ["good1", "good2"]

    def test_a_missing_key_error_is_never_swallowed(self, monkeypatch):
        def fake_enrich_batch(names):
            raise enrichment.EnrichmentUnavailable("no key")

        monkeypatch.setattr(enrichment, "enrich_batch", fake_enrich_batch)
        with pytest.raises(enrichment.EnrichmentUnavailable):
            enrichment.enrich_names(["a", "b"])

    def test_retries_are_reported_to_the_caller(self, monkeypatch):
        def fake_enrich_batch(names):
            if len(names) == 2:
                raise RuntimeError("boom")
            return {n: self._result(n) for n in names}

        monkeypatch.setattr(enrichment, "enrich_batch", fake_enrich_batch)
        notes = []
        enrichment.enrich_names(["a", "b"], on_note=notes.append)
        assert any("splitting" in note for note in notes)
