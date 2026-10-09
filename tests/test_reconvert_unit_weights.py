"""scripts/reconvert_unit_weights.py — recomputing stored weights for
sprig, bunch and can lines saved under the old name-based conversion."""

from backend.models import MeasureUnit, Recipe, RecipeIngredient, WeightSource
from scripts.reconvert_unit_weights import reconvert


def make_line(session, name, quantity, unit, grams, source=WeightSource.estimated):
    recipe = Recipe(slug=f"r-{name.replace(' ', '-')}-{quantity}", title=name)
    session.add(recipe)
    session.flush()
    line = RecipeIngredient(
        recipe_id=recipe.id,
        position=0,
        raw_text=f"{quantity} {unit.value} {name}",
        name=name,
        quantity=quantity,
        unit=unit,
        weight_grams=grams,
        weight_source=source,
    )
    session.add(line)
    session.commit()
    session.refresh(line)
    return line


class TestReconvert:
    def test_a_sprig_line_weighed_by_name_is_corrected(self, session):
        line = make_line(session, "lemon thyme", 6, MeasureUnit.sprig, 600.0)

        changed = reconvert(session)
        session.commit()

        assert [(old, new) for _, old, new in changed] == [(600.0, 24.0)]
        session.refresh(line)
        assert line.weight_grams == 24.0

    def test_a_stated_weight_is_left_alone(self, session):
        line = make_line(
            session, "lemon thyme", 6, MeasureUnit.sprig, 10.0, WeightSource.explicit
        )

        assert reconvert(session) == []
        session.refresh(line)
        assert line.weight_grams == 10.0

    def test_other_units_are_not_touched(self, session):
        line = make_line(session, "lemon", 2, MeasureUnit.piece, 999.0)

        assert reconvert(session) == []
        session.refresh(line)
        assert line.weight_grams == 999.0

    def test_rerunning_changes_nothing(self, session):
        make_line(session, "lemon thyme", 6, MeasureUnit.sprig, 600.0)
        reconvert(session)
        session.commit()

        assert reconvert(session) == []
