import re

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


#: The secret in the source, so public: a token signed with it can be forged
#: by anyone. Fine for local dev with auth off; refused with auth on.
DEFAULT_JWT_SECRET = "dev-secret-change-me"


class Settings(BaseSettings):
    """App configuration from environment variables (see DEVELOPMENT.md)."""

    # A validation error otherwise quotes every input value, secrets
    # included, into the deploy log or the journal.
    model_config = SettingsConfigDict(hide_input_in_errors=True)

    database_url: str = "sqlite:///./recipeflood.db"
    auth_enabled: bool = True
    google_client_id: str = ""
    jwt_secret: str = DEFAULT_JWT_SECRET
    allowed_emails: str = ""  # comma-separated bootstrap allowlist
    deploy_secret: str = ""
    deploy_trigger_path: str = ".deploy-trigger"

    # Recipes are world-readable by default (see SPEC.md "Visibility").
    # Set false to put the whole site behind the allowlist.
    public_read: bool = True

    currency_symbol: str = "$"

    # Origins the desktop app's webview calls the API from (see SPEC.md
    # "Desktop app sign-in"): comma-separated, and an empty value turns
    # CORS off entirely. The web app is same-origin and needs none of it.
    desktop_origins: str = "tauri://localhost,http://tauri.localhost,https://tauri.localhost"

    # Temporary cleanup switch: lets the Pantry page select several rows
    # at once and merge them all into one in a single action, instead of
    # the normal one-pair-at-a-time flow. Off by default — flip it on for
    # a tidy-up pass (e.g. after scripts/find_duplicate_ingredients.py
    # turns up a backlog) and back off once the pantry's settled, rather
    # than leaving a bulk-delete-adjacent tool permanently in the UI.
    pantry_multi_merge: bool = False

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

    # Google Sheets sync for the shopping list (see backend/sheet_sync.py
    # and SPEC.md "Google Sheet sync"). Sync is enabled only when both the
    # sheet id and the service-account key file are set; leaving either
    # blank makes every sync hook a no-op rather than erroring, so a
    # deployment that hasn't set this up yet behaves exactly as before.
    google_sheet_id: str = ""
    google_service_account_file: str = ""
    google_sheet_tab: str = "Shopping"

    @field_validator(
        "google_sheet_id",
        "google_service_account_file",
        "google_sheet_tab",
        "desktop_origins",
    )
    @classmethod
    def _strip_inline_comment(cls, value: str) -> str:
        # systemd's EnvironmentFile (how production loads .env) keeps an
        # inline "  # comment" as part of the value, so a tab named
        # "Shopping   # the default" would reach the Sheets API verbatim.
        # None of these values legitimately contains whitespace followed
        # by "#".
        return re.sub(r"\s+#.*$", "", value).strip()

    # OpenAI Images API — used only by scripts/generate_recipe_images.py.
    # Claude has no image-generation endpoint of its own, so placeholder
    # illustrations are a separate provider and a separate key. gpt-image-1
    # is scheduled for deprecation 2026-10-23 (OpenAI's replacements:
    # gpt-image-1-mini / gpt-image-1.5 / gpt-image-2) — kept as a setting
    # rather than a hardcoded literal so swapping it is a one-line change.
    openai_api_key: str = ""
    openai_image_model: str = "gpt-image-1"

    @model_validator(mode="after")
    def _auth_needs_a_private_secret(self):
        # Fleet spec CFG-2: with auth on, a missing or default JWT_SECRET
        # means anyone could mint a login token. Refuse to start (deploy.sh's
        # config preflight runs this before restarting the service).
        if self.auth_enabled and (not self.jwt_secret.strip() or self.jwt_secret == DEFAULT_JWT_SECRET):
            raise ValueError(
                "JWT_SECRET is unset or still the public default; set it to a long random "
                "string, e.g. `openssl rand -hex 32` (or AUTH_ENABLED=false for local dev)"
            )
        return self


settings = Settings()
