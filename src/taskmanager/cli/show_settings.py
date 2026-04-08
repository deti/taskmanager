"""CLI command to show application settings."""

from taskmanager.settings import get_settings


def show_settings() -> None:
    """Display all application settings as JSON.

    Shows the current values from all sources (defaults, config file, environment).
    """
    settings = get_settings()
    print(settings.model_dump_json(indent=2))  # noqa: T201


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    show_settings()
