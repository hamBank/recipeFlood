"""Shared fixtures.

Every test runs against a fresh in-memory SQLite database with auth
disabled, so the API tests exercise the real dependency graph (including
`get_optional_user`) without needing Google tokens.
"""

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend import auth as auth_module
from backend.config import settings
from backend.database import get_session
from backend.main import create_app
from backend.models import Category, Ingredient, User, UserRole


@pytest.fixture
def engine():
    # StaticPool keeps every connection pointed at the same in-memory DB,
    # which the request-scoped sessions in the app otherwise wouldn't share.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def app(engine, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    monkeypatch.setattr(settings, "public_read", True)
    application = create_app()

    def override():
        with Session(engine) as session:
            yield session

    application.dependency_overrides[get_session] = override
    return application


@pytest.fixture
def client(app):
    """Signed in as the local dev admin (AUTH_ENABLED=false)."""
    return TestClient(app)


@pytest.fixture
def guest_client(engine, monkeypatch):
    """An anonymous visitor.

    A *separate* app instance sharing the same database, with the two auth
    dependencies overridden rather than the global AUTH_ENABLED flag
    flipped — otherwise a test that uses both clients would knock the
    signed-in one out too. This is the fixture that proves costs stay
    private.
    """
    monkeypatch.setattr(settings, "public_read", True)
    application = create_app()

    def override_session():
        with Session(engine) as session:
            yield session

    def no_user():
        return None

    def unauthenticated():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    application.dependency_overrides[get_session] = override_session
    application.dependency_overrides[auth_module.get_optional_user] = no_user
    application.dependency_overrides[auth_module.get_current_user] = unauthenticated
    return TestClient(application)


@pytest.fixture
def admin(session):
    """The local dev admin.

    `AUTH_ENABLED=false` creates this row lazily on the first authenticated
    request, so the fixture has to tolerate it already existing rather than
    inserting a duplicate email.
    """
    user = session.exec(
        select(User).where(User.email == auth_module.DEV_USER_EMAIL)
    ).first()
    if user is None:
        user = User(
            email=auth_module.DEV_USER_EMAIL,
            name="Dev Admin",
            role=UserRole.admin,
            google_sub="dev",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
    return user


@pytest.fixture
def category(session):
    category = Category(slug="cake", name="Cake", sort_order=30)
    session.add(category)
    session.commit()
    session.refresh(category)
    return category


@pytest.fixture
def flour(session):
    """Plain flour, fully described: a price, a density and nutrition.

    Several tests lean on all three being present — it is the ingredient
    that lets a recipe produce a real weight, a real cost and a real
    nutrition panel.
    """
    ingredient = Ingredient(
        slug="plain-flour",
        name="plain flour",
        aliases=["flour"],
        package_size_grams=1000,
        cost_per_kg_cents=250,  # $2.50/kg
        density_g_per_ml=0.6,  # 1 AU cup (250ml) = 150g
        energy_kj=1480,
        calories_kcal=354,
        protein_g=10.0,
        fat_g=1.0,
        carbs_g=73.0,
        fibre_g=3.0,
        sodium_mg=2.0,
    )
    session.add(ingredient)
    session.commit()
    session.refresh(ingredient)
    return ingredient
