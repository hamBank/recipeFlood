"""SQLModel tables + API schemas.

Alembic autogenerate reads SQLModel.metadata via this module. See
DATA_MODEL.md for the narrative version of what follows.

Two numeric conventions worth knowing before reading anything else:

* **Money is integer cents per kilogram** (`Ingredient.cost_per_kg_cents`),
  never a float dollars-per-gram. Cents/kg gives four significant figures
  on a per-gram cost that is usually a fraction of a cent — enough
  resolution to price a 2g pinch of saffron and a 1kg bag of flour with
  the same field. `cost_per_gram` is derived for display only.
* **Weight is always grams** (`RecipeIngredient.weight_grams`), a float
  because a converted 1/3 cup rarely lands on an integer.
"""

from datetime import date, datetime, timezone
from enum import Enum

# SAEnum, not Enum: a bare `Enum` here shadows enum.Enum and every
# `class Foo(str, Enum)` below stops being an enum.
from sqlalchemy import JSON, Column
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel  # noqa: F401


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    admin = "admin"
    user = "user"


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    google_sub: str | None = Field(default=None, unique=True, index=True)
    email: str = Field(unique=True, index=True)
    name: str = ""
    avatar_url: str | None = None
    role: UserRole = Field(default=UserRole.user)
    is_active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class UserRead(SQLModel):
    id: int
    email: str
    name: str
    avatar_url: str | None
    role: UserRole
    is_active: bool


class UserUpdate(SQLModel):
    name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class UserInvite(SQLModel):
    email: str
    name: str = ""
    role: UserRole = UserRole.user


# --------------------------------------------------------------------------
# Master ingredient list
# --------------------------------------------------------------------------


class IngredientSource(str, Enum):
    """Where this item is usually bought.

    Stored as a plain string column rather than a database ENUM. The first
    seven values were a guess; importing a real shopping list added seven
    more, and that list will keep growing. A VARCHAR plus this class for
    validation means the next addition is a one-line change instead of an
    `ALTER TYPE` that behaves differently on SQLite and Postgres.
    """

    markets = "markets"
    supermarket = "supermarket"
    butcher = "butcher"
    nut_shop = "nut_shop"
    deli = "deli"
    asian_grocery = "asian_grocery"
    # Added from the shopping list — these are where the shopping actually
    # happens, as opposed to where I assumed it did.
    fishmonger = "fishmonger"
    bakery = "bakery"
    bottle_shop = "bottle_shop"
    cake_supplies = "cake_supplies"
    chemist = "chemist"
    hardware = "hardware"
    newsagent = "newsagent"
    other = "other"


class Ingredient(SQLModel, table=True):
    """A pantry item, priced and (eventually) nutritionally described once,
    then referenced by every recipe that uses it.

    Nutrition columns are all "per 100g" and all nullable: a recipe's
    nutrition panel reports the share of its weight it could actually
    account for rather than silently under-reporting (see nutrition.py).
    """

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str = Field(index=True)
    # Alternate spellings the importer matches against ("fetta"/"feta",
    # "coriander"/"cilantro"). Lowercased on write.
    aliases: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    package_size_grams: float | None = None
    cost_per_kg_cents: int | None = None
    # Where the price came from and when — mirrors nutrition_source /
    # nutrition_updated_at below. "manual" once a human edits it via the
    # Pantry page; an enrichment script sets its own label (e.g. "AI
    # estimate (mid-season, 2026-08)") so a rough guess is never mistaken
    # for a price someone actually paid.
    cost_source: str | None = None
    cost_updated_at: datetime | None = None
    # native_enum=False + create_constraint=False: stored as a plain VARCHAR
    # with no database-level CHECK, so adding a shop needs no migration —
    # but SQLAlchemy still hands back an IngredientSource on read rather
    # than a bare string, which every caller would otherwise have to
    # remember. Names and values are identical on this enum, so what lands
    # in the column is the value either way.
    source: IngredientSource = Field(
        default=IngredientSource.supermarket,
        sa_column=Column(
            SAEnum(IngredientSource, native_enum=False, create_constraint=False, length=32),
            nullable=False,
            server_default="supermarket",
        ),
    )

    # False for the things that come home from the shops but never go in a
    # recipe — batteries, shampoo, cat litter. They stay in the pantry so it
    # remains a complete shopping lookup, but they are filtered out of the
    # ingredient pickers and the "needs a price" queue.
    is_food: bool = Field(default=True, index=True)

    # Conversion helpers. density_g_per_ml turns "1 cup" into grams;
    # grams_per_piece turns "2 onions" into grams. Both optional — without
    # them the converter falls back to the keyword table in units.py.
    density_g_per_ml: float | None = None
    grams_per_piece: float | None = None

    # Nutrition per 100g. Australian labelling leads with kilojoules;
    # calories are kept alongside because most sources quote them.
    energy_kj: float | None = None
    calories_kcal: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    saturated_fat_g: float | None = None
    carbs_g: float | None = None
    sugars_g: float | None = None
    fibre_g: float | None = None
    sodium_mg: float | None = None
    # A label, not a boolean: "packet" or "AUSNUT" reads as real, "AI
    # estimate" reads as a guess to be checked — see ingredient_enrichment.py.
    nutrition_source: str | None = None
    nutrition_updated_at: datetime | None = None

    notes: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class IngredientNutrition(SQLModel):
    """Per-100g nutrition, split out so it can be PATCHed on its own by the
    (planned) bulk nutrition-population process."""

    energy_kj: float | None = None
    calories_kcal: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    saturated_fat_g: float | None = None
    carbs_g: float | None = None
    sugars_g: float | None = None
    fibre_g: float | None = None
    sodium_mg: float | None = None
    nutrition_source: str | None = None


class IngredientCreate(SQLModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    package_size_grams: float | None = Field(default=None, gt=0)
    cost_per_kg_cents: int | None = Field(default=None, ge=0)
    source: IngredientSource = IngredientSource.supermarket
    density_g_per_ml: float | None = Field(default=None, gt=0)
    grams_per_piece: float | None = Field(default=None, gt=0)
    is_food: bool = True
    notes: str | None = None


class IngredientUpdate(SQLModel):
    name: str | None = None
    aliases: list[str] | None = None
    package_size_grams: float | None = Field(default=None, gt=0)
    cost_per_kg_cents: int | None = Field(default=None, ge=0)
    source: IngredientSource | None = None
    cost_source: str | None = None
    density_g_per_ml: float | None = Field(default=None, gt=0)
    grams_per_piece: float | None = Field(default=None, gt=0)
    is_food: bool | None = None
    notes: str | None = None
    # Nutrition fields are updatable through the same PATCH.
    energy_kj: float | None = None
    calories_kcal: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    saturated_fat_g: float | None = None
    carbs_g: float | None = None
    sugars_g: float | None = None
    fibre_g: float | None = None
    sodium_mg: float | None = None
    nutrition_source: str | None = None


class IngredientRead(SQLModel):
    id: int
    slug: str
    name: str
    aliases: list[str]
    package_size_grams: float | None
    cost_per_kg_cents: int | None
    cost_per_gram: float | None  # derived: dollars, 5dp — display only
    package_cost_cents: int | None  # derived: cost of one usual package
    cost_source: str | None
    cost_updated_at: datetime | None
    source: IngredientSource
    is_food: bool
    density_g_per_ml: float | None
    grams_per_piece: float | None
    energy_kj: float | None
    calories_kcal: float | None
    protein_g: float | None
    fat_g: float | None
    saturated_fat_g: float | None
    carbs_g: float | None
    sugars_g: float | None
    fibre_g: float | None
    sodium_mg: float | None
    nutrition_source: str | None
    nutrition_updated_at: datetime | None
    has_nutrition: bool
    recipe_count: int = 0
    notes: str | None


# --------------------------------------------------------------------------
# Recipe taxonomy
# --------------------------------------------------------------------------


class Tag(SQLModel, table=True):
    """A label on a recipe. One concept, two roles.

    Most tags are free-form and arrive from the source blog — 266 of them,
    over half used exactly once ("moghrabieh", "carparccio"). They are for
    search and for the "more like this" chips, not for navigation.

    A small curated set is flagged `is_section`: Cake, Salad, Dessert,
    Bread. Those are the site's navigation, ordered by `sort_order`. The
    distinction is a property of the *tag*, not of the recipe — so a recipe
    just carries tags, and some of them happen to be sections.

    Why not a separate Category table with exactly one per recipe: it makes
    the model carry two concepts to express one idea, and it forces a
    chocolate tart to choose between Dessert and Pastry & Tarts. Why not
    tags alone: the blog's own labels reach only 68% of the collection from
    a top-20 nav, stranding about a hundred recipes behind search.
    """

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    # Section tags form the navigation; everything else is free-form.
    is_section: bool = Field(default=False, index=True)
    sort_order: int = 0  # ordering within the nav; ignored for free tags
    description: str | None = None


class RecipeTagLink(SQLModel, table=True):
    recipe_id: int = Field(foreign_key="recipe.id", primary_key=True)
    tag_id: int = Field(foreign_key="tag.id", primary_key=True)


class TagRead(SQLModel):
    id: int
    slug: str
    name: str
    is_section: bool
    sort_order: int
    description: str | None
    recipe_count: int = 0


class TagCreate(SQLModel):
    name: str
    slug: str | None = None  # derived from the name when omitted
    is_section: bool = False
    sort_order: int = 0
    description: str | None = None


class TagUpdate(SQLModel):
    """Also how a tag is promoted to a section, or demoted back."""

    name: str | None = None
    is_section: bool | None = None
    sort_order: int | None = None
    description: str | None = None


# --------------------------------------------------------------------------
# Recipes
# --------------------------------------------------------------------------


class ImportSource(str, Enum):
    manual = "manual"
    blog = "blog"  # scraped from foobie-rcp.blogspot.com
    ai_image = "ai_image"  # phase 2: photo of a recipe
    ai_paste = "ai_paste"  # phase 2: pasted text


class Recipe(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)
    title: str = Field(index=True)
    description: str | None = None

    # Image path relative to the upload dir ("recipes/flax-bread.jpg"), or
    # null for the ~86% of scraped posts that had no photo. image_source_url
    # keeps the original remote URL for provenance after self-hosting.
    image_path: str | None = None
    image_source_url: str | None = None

    # "Added Date" in the spec. Defaults to now for manual entry; the blog
    # importer backdates it to the original post date.
    added_date: datetime = Field(default_factory=utcnow, index=True)

    prep_minutes: int | None = None
    cook_minutes: int | None = None
    # Null = derive as prep + cook. Set explicitly when the recipe's real
    # total includes something neither covers (proving, chilling, marinating).
    total_minutes_override: int | None = None

    servings: int | None = None
    servings_note: str | None = None  # "makes 24 biscuits", "serves 8-10"

    storage: str | None = None
    nutrition_note: str | None = None  # free text alongside the computed panel

    source_url: str | None = None
    source_name: str | None = None

    units_system: str = "au"  # conversion convention for this recipe's amounts

    import_source: ImportSource = Field(default=ImportSource.manual)
    # Set by the importers when a field was guessed rather than read. Drives
    # the "needs review" queue so nothing AI-derived is silently trusted.
    needs_review: bool = Field(default=False, index=True)
    review_note: str | None = None

    is_published: bool = Field(default=True, index=True)
    created_by: int | None = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class MeasureUnit(str, Enum):
    """Units an amount can be written in. `piece` covers countable things
    ("2 eggs"); `to_taste` and `pinch` are unquantifiable by design."""

    g = "g"
    kg = "kg"
    mg = "mg"
    ml = "ml"
    l = "l"
    cup = "cup"
    tbsp = "tbsp"
    dsp = "dsp"  # dessertspoon, 10ml — appears in older AU recipes
    tsp = "tsp"
    fl_oz = "fl_oz"
    oz = "oz"
    lb = "lb"
    piece = "piece"
    slice = "slice"
    clove = "clove"
    bunch = "bunch"
    sprig = "sprig"
    can = "can"
    pinch = "pinch"
    to_taste = "to_taste"


class WeightSource(str, Enum):
    """How `weight_grams` was arrived at — surfaced in the UI so a converted
    weight is never mistaken for one the recipe actually stated."""

    explicit = "explicit"  # the recipe gave a weight
    converted = "converted"  # volume x density, or count x grams_per_piece
    estimated = "estimated"  # keyword-table density, no linked ingredient
    unknown = "unknown"  # not convertible ("to taste", "1 bunch mint")


class RecipeIngredient(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipe.id", index=True)
    position: int = 0

    # Null until matched to the master list. raw_text always survives so a
    # bad match can be re-done from the original line.
    ingredient_id: int | None = Field(
        default=None, foreign_key="ingredient.id", index=True
    )
    raw_text: str
    name: str

    quantity: float | None = None
    quantity_max: float | None = None  # "2-3 tbsp" -> quantity=2, max=3
    unit: MeasureUnit | None = None

    weight_grams: float | None = None
    weight_source: WeightSource = Field(default=WeightSource.unknown)

    note: str | None = None  # "finely chopped", "at room temperature"
    optional: bool = False
    group: str | None = None  # "For the sauce", "Topping"


class RecipeIngredientIn(SQLModel):
    ingredient_id: int | None = None
    raw_text: str | None = None  # defaults to a rendering of the parts
    name: str
    quantity: float | None = None
    quantity_max: float | None = None
    unit: MeasureUnit | None = None
    weight_grams: float | None = None  # omit to let the converter fill it
    note: str | None = None
    optional: bool = False
    group: str | None = None


class RecipeIngredientRead(SQLModel):
    id: int
    position: int
    ingredient_id: int | None
    raw_text: str
    name: str
    quantity: float | None
    quantity_max: float | None
    unit: MeasureUnit | None
    weight_grams: float | None
    weight_source: WeightSource
    note: str | None
    optional: bool
    group: str | None
    # Populated only for signed-in users (costs are not public — SPEC.md).
    cost_cents: int | None = None


class RecipeStep(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipe.id", index=True)
    position: int = 0
    text: str


class RecipeStepIn(SQLModel):
    text: str


class RecipeStepRead(SQLModel):
    id: int
    position: int
    text: str


class PreparedEvent(SQLModel, table=True):
    """One "we cooked this" entry. The recipe's Last Prepared Date is the
    newest of these — kept as a log rather than a single column so
    "haven't made this in a year" and "our most-cooked" both work."""

    id: int | None = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipe.id", index=True)
    prepared_on: date
    user_id: int | None = Field(default=None, foreign_key="user.id")
    rating: int | None = Field(default=None, ge=1, le=5)
    note: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class PreparedEventCreate(SQLModel):
    prepared_on: date | None = None  # defaults to today
    rating: int | None = Field(default=None, ge=1, le=5)
    note: str | None = None


class PreparedEventRead(SQLModel):
    id: int
    recipe_id: int
    prepared_on: date
    user_id: int | None
    user_name: str | None
    rating: int | None
    note: str | None


class NutritionRead(SQLModel):
    """Computed from the linked master ingredients, never stored.

    `coverage` is the fraction of the recipe's total known weight that came
    from ingredients that actually have nutrition data. A panel with
    coverage 0.4 is showing 40% of the food, and the UI says so rather than
    presenting a confident-looking undercount.
    """

    energy_kj: float | None = None
    calories_kcal: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    saturated_fat_g: float | None = None
    carbs_g: float | None = None
    sugars_g: float | None = None
    fibre_g: float | None = None
    sodium_mg: float | None = None
    coverage: float = 0.0
    covered_grams: float = 0.0
    total_grams: float = 0.0
    per_serving: bool = False


class RecipeCost(SQLModel):
    """Signed-in users only. `known_fraction` is the share of ingredients
    that had a price, for the same reason nutrition reports coverage."""

    total_cents: int = 0
    per_serving_cents: int | None = None
    known_fraction: float = 0.0
    priced_count: int = 0
    ingredient_count: int = 0


class RecipeCreate(SQLModel):
    title: str
    description: str | None = None
    image_path: str | None = None
    image_source_url: str | None = None
    added_date: datetime | None = None
    prep_minutes: int | None = Field(default=None, ge=0)
    cook_minutes: int | None = Field(default=None, ge=0)
    total_minutes_override: int | None = Field(default=None, ge=0)
    servings: int | None = Field(default=None, gt=0)
    servings_note: str | None = None
    storage: str | None = None
    nutrition_note: str | None = None
    source_url: str | None = None
    source_name: str | None = None
    units_system: str | None = None
    is_published: bool = True
    # Every label, section or not — whether a tag is a section is a
    # property of the tag, not of this recipe.
    tags: list[str] = Field(default_factory=list)
    ingredients: list[RecipeIngredientIn] = Field(default_factory=list)
    steps: list[RecipeStepIn] = Field(default_factory=list)


class RecipeUpdate(SQLModel):
    title: str | None = None
    description: str | None = None
    image_path: str | None = None
    image_source_url: str | None = None
    added_date: datetime | None = None
    prep_minutes: int | None = Field(default=None, ge=0)
    cook_minutes: int | None = Field(default=None, ge=0)
    total_minutes_override: int | None = Field(default=None, ge=0)
    servings: int | None = Field(default=None, gt=0)
    servings_note: str | None = None
    storage: str | None = None
    nutrition_note: str | None = None
    source_url: str | None = None
    source_name: str | None = None
    units_system: str | None = None
    is_published: bool | None = None
    needs_review: bool | None = None
    review_note: str | None = None
    # Omit to leave untouched; pass a list to replace wholesale.
    tags: list[str] | None = None
    ingredients: list[RecipeIngredientIn] | None = None
    steps: list[RecipeStepIn] | None = None


class RecipeSummary(SQLModel):
    """The list/grid projection — deliberately free of ingredients, steps
    and cost so the index page is one query per page, not one per card."""

    id: int
    slug: str
    title: str
    description: str | None
    image_path: str | None
    added_date: datetime
    total_minutes: int | None
    servings: int | None
    # `tags` is every label; `sections` is the navigation subset of it,
    # in nav order. The card badges sections[0].
    tags: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    last_prepared_on: date | None = None
    prepared_count: int = 0
    needs_review: bool = False
    is_published: bool = True


class RecipeRead(SQLModel):
    id: int
    slug: str
    title: str
    description: str | None
    image_path: str | None
    image_source_url: str | None
    added_date: datetime
    prep_minutes: int | None
    cook_minutes: int | None
    total_minutes: int | None
    total_minutes_override: int | None
    servings: int | None
    servings_note: str | None
    storage: str | None
    nutrition_note: str | None
    source_url: str | None
    source_name: str | None
    units_system: str
    import_source: ImportSource
    needs_review: bool
    review_note: str | None
    is_published: bool
    created_at: datetime
    updated_at: datetime
    tags: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    ingredients: list[RecipeIngredientRead] = Field(default_factory=list)
    steps: list[RecipeStepRead] = Field(default_factory=list)
    last_prepared_on: date | None = None
    prepared_count: int = 0
    prepared_events: list[PreparedEventRead] = Field(default_factory=list)
    nutrition: NutritionRead | None = None
    nutrition_per_serving: NutritionRead | None = None
    cost: RecipeCost | None = None  # signed-in only


# --------------------------------------------------------------------------
# Cooking lists and the shopping list
# --------------------------------------------------------------------------


class CookList(SQLModel, table=True):
    """A set of recipes planned for one date — a week's cooking, a dinner
    party, a Christmas menu.

    The date is the identity of the list, which is why it isn't nullable:
    "what are we cooking" is always a question about a particular week. The
    description is where a list earns a name ("Anna's birthday", "camping
    food") and is usually empty.

    Two lists can share a date. Nothing enforces uniqueness because a week
    of dinners and the cake for Saturday are legitimately separate lists
    that happen to start on the same Monday.
    """

    id: int | None = Field(default=None, primary_key=True)
    cook_date: date = Field(index=True)
    description: str | None = None
    notes: str | None = None
    created_by: int | None = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CookListRecipe(SQLModel, table=True):
    """A recipe's membership of a cooking list.

    `servings` is the phase-2 scaling hook: null means "as written", a
    number means scale the ingredients to that many serves. The scale
    factor is computed live from `Recipe.servings` rather than frozen here,
    so fixing a recipe's serving size later corrects every list that used
    it.
    """

    id: int | None = Field(default=None, primary_key=True)
    cook_list_id: int = Field(foreign_key="cooklist.id", index=True)
    recipe_id: int = Field(foreign_key="recipe.id", index=True)
    position: int = 0
    servings: int | None = Field(default=None, gt=0)
    note: str | None = None


class ShoppingItemSource(str, Enum):
    manual = "manual"  # typed straight onto the list
    cook_list = "cook_list"  # aggregated from a cooking list's recipes


class ShoppingItem(SQLModel, table=True):
    """One line on the shopping list.

    There is exactly one shopping list and it is permanent — no
    `ShoppingList` table, just these rows. A list you clear and rebuild
    every week is a list that loses the "we always need milk" line, and the
    alternative (a list per shop, per week) is bookkeeping nobody does.

    Items are checked off rather than deleted so a half-finished shop
    survives closing the phone, and so "what did we buy" is answerable
    until the list is cleared.

    `ingredient_id` is nullable for the same reason `RecipeIngredient`'s is:
    an unmatched recipe line still belongs on the list as plain text rather
    than disappearing because the pantry has never heard of it.
    """

    id: int | None = Field(default=None, primary_key=True)
    ingredient_id: int | None = Field(
        default=None, foreign_key="ingredient.id", index=True
    )
    name: str  # display text; the ingredient's name when linked

    # Aggregated amount. weight_grams is what merging actually works on;
    # quantity/unit survive for the lines that have no weight ("1 bunch
    # coriander") so the list can still say something useful.
    weight_grams: float | None = None
    quantity: float | None = None
    # VARCHAR, not the native `measureunit` enum the recipe tables use.
    # That type already exists in Postgres from the baseline migration, and
    # a second CREATE TYPE for it fails — the same dual-dialect trap
    # IngredientSource documents above.
    unit: MeasureUnit | None = Field(
        default=None,
        sa_column=Column(
            SAEnum(MeasureUnit, native_enum=False, create_constraint=False, length=16),
            nullable=True,
        ),
    )
    note: str | None = None

    is_checked: bool = Field(default=False, index=True)
    checked_at: datetime | None = None

    source: ShoppingItemSource = Field(
        default=ShoppingItemSource.manual,
        sa_column=Column(
            SAEnum(
                ShoppingItemSource,
                native_enum=False,
                create_constraint=False,
                length=16,
            ),
            nullable=False,
            server_default="manual",
        ),
    )
    # Which list put it here, and which recipes contributed — kept so the
    # UI can answer "why is 400g of onion on my list" without re-running
    # the aggregation. A list of {"recipe": str, "amount": str} dicts.
    cook_list_id: int | None = Field(
        default=None, foreign_key="cooklist.id", index=True
    )
    contributions: list[dict] = Field(default_factory=list, sa_column=Column(JSON))

    added_at: datetime = Field(default_factory=utcnow)


# --- schemas ---------------------------------------------------------------


class CookListRecipeIn(SQLModel):
    recipe_id: int
    servings: int | None = Field(default=None, gt=0)
    note: str | None = None


class CookListRecipeRead(SQLModel):
    id: int
    recipe_id: int
    position: int
    servings: int | None
    note: str | None
    # Denormalised for the detail page, which would otherwise need a
    # request per row.
    slug: str
    title: str
    image_path: str | None
    base_servings: int | None
    # False when `servings` was asked for but the recipe has no serving
    # size to scale from — the UI says so rather than silently not scaling.
    scalable: bool = True
    scale_factor: float = 1.0


class CookListCreate(SQLModel):
    cook_date: date | None = None  # defaults to today
    description: str | None = None
    notes: str | None = None
    recipes: list[CookListRecipeIn] = Field(default_factory=list)


class CookListUpdate(SQLModel):
    cook_date: date | None = None
    description: str | None = None
    notes: str | None = None
    # Omit to leave membership alone; pass a list to replace it wholesale.
    recipes: list[CookListRecipeIn] | None = None


class CookListRead(SQLModel):
    id: int
    cook_date: date
    description: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    recipe_count: int = 0
    recipes: list[CookListRecipeRead] = Field(default_factory=list)


class ShoppingItemCreate(SQLModel):
    name: str
    ingredient_id: int | None = None
    weight_grams: float | None = Field(default=None, ge=0)
    quantity: float | None = Field(default=None, ge=0)
    unit: MeasureUnit | None = None
    note: str | None = None


class ShoppingItemUpdate(SQLModel):
    name: str | None = None
    weight_grams: float | None = Field(default=None, ge=0)
    quantity: float | None = Field(default=None, ge=0)
    unit: MeasureUnit | None = None
    note: str | None = None
    is_checked: bool | None = None


class ShoppingItemRead(SQLModel):
    id: int
    ingredient_id: int | None
    name: str
    weight_grams: float | None
    quantity: float | None
    unit: MeasureUnit | None
    note: str | None
    is_checked: bool
    checked_at: datetime | None
    source: ShoppingItemSource
    cook_list_id: int | None
    contributions: list[dict] = Field(default_factory=list)
    added_at: datetime
    # Where this gets bought, so the list can be walked shop by shop.
    # "other" when the item isn't linked to a pantry row.
    shop: str = IngredientSource.other.value
    amount_text: str = ""  # "400 g", "1 bunch" — rendered once, server-side
    cost_cents: int | None = None  # signed-in only, null when unpriced


class ShoppingListRead(SQLModel):
    """The whole list, already grouped by shop.

    Grouping server-side keeps the ordering rule (shops in a fixed walking
    order, checked items last) in one place instead of duplicated in every
    client.
    """

    items: list[ShoppingItemRead] = Field(default_factory=list)
    shops: list[str] = Field(default_factory=list)  # in display order
    total_count: int = 0
    checked_count: int = 0
    # Signed-in only: what the unchecked items add up to, and how much of
    # the list that covers — same honesty rule as RecipeCost.
    total_cents: int | None = None
    priced_fraction: float = 0.0


class AddToShoppingResult(SQLModel):
    added: int = 0
    merged: int = 0
    items: list[ShoppingItemRead] = Field(default_factory=list)
    # Recipe lines that could not be turned into an amount ("salt to
    # taste"). Reported rather than dropped.
    skipped: list[str] = Field(default_factory=list)
