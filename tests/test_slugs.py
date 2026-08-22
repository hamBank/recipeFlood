from backend.slugs import slugify, unique_slug


def test_slugify_strips_punctuation_and_case():
    assert slugify("Salt & Pepper Squid!") == "salt-pepper-squid"
    assert slugify("Goat's cheese, rocket") == "goat-s-cheese-rocket"


def test_slugify_handles_accents_and_emptiness():
    assert slugify("Crème brûlée") == "creme-brulee"
    assert slugify("!!!") == "untitled"
    assert slugify("") == "untitled"


def test_slugify_truncates_without_a_trailing_dash():
    slug = slugify("a" * 50 + " " + "b" * 50, max_length=60)
    assert len(slug) <= 60
    assert not slug.endswith("-")


def test_unique_slug_suffixes_collisions():
    # The blog really does have two posts called "Croissant".
    taken = {"croissant"}
    assert unique_slug("Croissant", lambda s: s in taken) == "croissant-2"
    taken.add("croissant-2")
    assert unique_slug("Croissant", lambda s: s in taken) == "croissant-3"


def test_unique_slug_leaves_a_free_slug_alone():
    assert unique_slug("Flax Bread", lambda s: False) == "flax-bread"
