from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """App configuration from environment variables (see DEVELOPMENT.md)."""

    database_url: str = "sqlite:///./recipeflood.db"
    auth_enabled: bool = True
    google_client_id: str = ""
    jwt_secret: str = "dev-secret-change-me"
    allowed_emails: str = ""  # comma-separated bootstrap allowlist
    deploy_secret: str = ""
    deploy_trigger_path: str = ".deploy-trigger"

    # Recipes are world-readable by default (see SPEC.md "Visibility").
    # Set false to put the whole site behind the allowlist.
    public_read: bool = True

    currency_symbol: str = "$"

    # Volume->weight conversion convention. "au" = 250ml cup, 20ml tbsp
    # (correct for the scraped blog); "us" = 240ml cup, 15ml tbsp.
    # See backend/units.py.
    units_system: str = "au"

    # Where uploaded / imported recipe images are written and served from.
    upload_dir: str = "backend/uploads"

    # Anthropic API — used only by the offline import scripts and the
    # (phase 2) AI import endpoints. Unset = those features report
    # "not configured" rather than failing at import time.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    # OpenAI Images API — used only by scripts/generate_recipe_images.py.
    # Claude has no image-generation endpoint of its own, so placeholder
    # illustrations are a separate provider and a separate key. gpt-image-1
    # is scheduled for deprecation 2026-10-23 (OpenAI's replacements:
    # gpt-image-1-mini / gpt-image-1.5 / gpt-image-2) — kept as a setting
    # rather than a hardcoded literal so swapping it is a one-line change.
    openai_api_key: str = ""
    openai_image_model: str = "gpt-image-1"


settings = Settings()
