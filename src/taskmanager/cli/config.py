"""Configuration management CLI commands.

This module provides the config sub-command with operations to:
- Initialize default config file
- Show current configuration with source annotations
- Display config file path
- Set configuration values
"""

import os
import tomllib
from typing import Annotated, Any

import tomli_w
import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from taskmanager.settings import CONFIG_FILE_PATH, Settings, TOMLSyntaxError, get_settings


app = typer.Typer(help="Manage configuration — init, show, path, set.")
console = Console()
console_err = Console(stderr=True)


# Template for default config with comments
DEFAULT_CONFIG_TEMPLATE = """\
# TaskManager Configuration File
#
# This file provides default values for the taskmanager application.
# Values defined here override built-in defaults but are themselves
# overridden by environment variables.
#
# Precedence order: environment variables > this file > built-in defaults

# Application metadata
# app_name = "taskmanager"

# Debugging and logging
# debug = false
# log_level = "INFO"          # Options: CRITICAL, ERROR, WARNING, INFO, DEBUG
# log_format = "text"         # Options: text, json

# Runtime environment
# environment = "development"  # Options: development, production, test

# Task execution settings
# default_shell = "/bin/bash"
# subprocess_timeout = 300     # Timeout in seconds for subprocess execution

# History and retention
# history_retention_days = 30  # Number of days to retain task execution history

# API server settings
# api_host = "127.0.0.1"
# api_port = 8000

# Database configuration
# db_url = "sqlite:///~/.taskmanager/taskmanager.db"
"""


@app.command()
def init(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing config file if present."),
    ] = False,
) -> None:
    """Create a new configuration file with default values and comments.

    Creates ~/.taskmanager/config.toml with all available settings documented.
    Use --force to overwrite an existing config file.
    """
    config_path = CONFIG_FILE_PATH
    config_dir = config_path.parent

    # Check if file already exists before creating anything
    file_existed = config_path.exists()

    if file_existed and not force:
        console_err.print(
            f"[yellow]Warning:[/yellow] Config file already exists: {config_path}"
        )
        console_err.print("Use --force to overwrite.")
        raise typer.Exit(code=1)

    # Create directory if it doesn't exist
    if not config_dir.exists():
        config_dir.mkdir(parents=True, mode=0o755)
        console.print(f"[green]✓[/green] Created config directory: {config_dir}")

    # Write default config template
    config_path.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
    action = "Overwritten" if file_existed else "Created"
    console.print(f"[green]✓[/green] {action} config file: {config_path}")
    console.print("\nEdit the file to customize your settings.")


@app.command()
def show() -> None:
    """Display current configuration values with their sources.

    Shows each setting's value and where it came from: built-in default,
    config file, or environment variable. Helps debug configuration issues.
    """
    try:
        settings = get_settings()
    except (TOMLSyntaxError, ValidationError) as e:
        console_err.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1) from None

    # Load TOML config to check which values are from file
    toml_values: dict[str, Any] = {}
    if CONFIG_FILE_PATH.exists():
        try:
            with CONFIG_FILE_PATH.open("rb") as f:
                toml_values = tomllib.load(f)
        except tomllib.TOMLDecodeError:
            pass  # Already caught by get_settings above

    # Get all field names from settings model class
    field_names = list(Settings.model_fields.keys())

    # Build table
    table = Table(title="Current Configuration", show_header=True, header_style="bold")
    table.add_column("Setting", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")
    table.add_column("Source", style="green")

    for field_name in field_names:
        # Skip internal/excluded fields
        field_info = Settings.model_fields[field_name]
        if field_info.exclude:
            continue

        value = getattr(settings, field_name)

        # Determine source
        # Check environment variable (case-insensitive)
        env_var_name = field_name.upper()
        if env_var_name in os.environ:
            source = f"env:{env_var_name}"
        elif field_name in toml_values:
            source = "config"
        else:
            source = "default"

        # Format value
        if isinstance(value, bool):
            value_str = str(value).lower()
        elif isinstance(value, str):
            value_str = value
        else:
            value_str = str(value)

        table.add_row(field_name, value_str, source)

    console.print(table)
    console.print(f"\nConfig file: {CONFIG_FILE_PATH}")
    if not CONFIG_FILE_PATH.exists():
        console.print("[yellow]Config file not found. Run 'config init' to create it.[/yellow]")


@app.command()
def path() -> None:
    """Print the path to the configuration file.

    Shows the expected config file location, whether it exists or not.
    """
    config_path = CONFIG_FILE_PATH
    if config_path.exists():
        console.print(f"{config_path}")
    else:
        console.print(f"{config_path} [yellow](not found)[/yellow]")


@app.command()
def set(  # noqa: PLR0912, PLR0915
    key: Annotated[str, typer.Argument(help="Configuration key to set (e.g., log_level, debug).")],
    value: Annotated[str, typer.Argument(help="New value for the configuration key.")],
) -> None:
    """Update a configuration value in the TOML file.

    The key must be a valid setting name. Values are validated against
    the setting's type before writing. Restart or clear cache to apply changes.
    """
    settings = get_settings()

    # Validate key exists in Settings model class
    if key not in Settings.model_fields:
        console_err.print(f"[red]Error:[/red] Unknown configuration key: {key}")
        console_err.print("\nAvailable keys:")
        for field_name in Settings.model_fields:
            field_info = Settings.model_fields[field_name]
            if not field_info.exclude:
                console_err.print(f"  - {field_name}")
        raise typer.Exit(code=1)

    # Skip excluded fields
    field_info = Settings.model_fields[key]
    if field_info.exclude:
        console_err.print(f"[red]Error:[/red] Cannot set excluded field: {key}")
        raise typer.Exit(code=1)

    # Convert value to appropriate type based on field annotation
    field_type = field_info.annotation
    converted_value: Any

    try:
        # Handle bool specially
        if field_type is bool:
            if value.lower() in ("true", "yes", "1", "on"):
                converted_value = True
            elif value.lower() in ("false", "no", "0", "off"):
                converted_value = False
            else:
                msg = f"Invalid boolean value: {value}"
                raise ValueError(msg)
        # Handle int
        elif field_type is int:
            converted_value = int(value)
        # Handle str (including Literal types which are str-based)
        else:
            converted_value = value
    except ValueError as e:
        console_err.print(f"[red]Error:[/red] Invalid value for {key}: {e}")
        raise typer.Exit(code=1) from None

    # Validate the value by creating a temporary Settings instance
    # This will check Literal values, validators, etc.
    try:
        test_data = {key: converted_value}
        # We need to provide all required fields for validation
        # Use the current settings as a base
        Settings.model_validate({**settings.model_dump(), **test_data})
    except ValidationError as e:
        console_err.print(f"[red]Error:[/red] Invalid value for {key}:")
        for error in e.errors():
            console_err.print(f"  {error['msg']}")
        raise typer.Exit(code=1) from None

    # Load existing config or create empty dict
    config_path = CONFIG_FILE_PATH
    config_dir = config_path.parent

    if config_path.exists():
        try:
            with config_path.open("rb") as f:
                config_data = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            console_err.print(f"[red]Error:[/red] Invalid TOML syntax in {config_path}: {e}")
            raise typer.Exit(code=1) from None
    else:
        # Create directory if needed
        if not config_dir.exists():
            config_dir.mkdir(parents=True, mode=0o755)
        config_data = {}

    # Update the value
    old_value = config_data.get(key)
    config_data[key] = converted_value

    # Write back to file
    try:
        with config_path.open("wb") as f:
            tomli_w.dump(config_data, f)
    except OSError as e:
        console_err.print(f"[red]Error:[/red] Failed to write config file: {e}")
        raise typer.Exit(code=1) from None

    # Show result
    if old_value is not None:
        console.print(f"[green]✓[/green] Updated {key}: {old_value} → {converted_value}")
    else:
        console.print(f"[green]✓[/green] Set {key} = {converted_value}")
    console.print(f"\nConfig file: {config_path}")
    console.print("[dim]Note: Clear settings cache or restart to apply changes.[/dim]")
