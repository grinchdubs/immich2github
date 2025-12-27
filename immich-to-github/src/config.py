"""Configuration management for Immich to GitHub sync."""

import os
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings


class ImmichConfig(BaseSettings):
    """Immich API configuration."""

    api_url: str = Field(..., validation_alias="IMMICH_API_URL")
    api_key: str = Field(..., validation_alias="IMMICH_API_KEY")

    class Config:
        env_file = ".env"
        extra = "ignore"


class GitHubConfig(BaseSettings):
    """GitHub configuration."""

    token: str = Field(..., validation_alias="GITHUB_TOKEN")

    class Config:
        env_file = ".env"
        extra = "ignore"


class Config:
    """Main configuration class."""

    def __init__(self, config_path: str = "config.yaml"):
        """Initialize configuration from YAML file and environment variables."""
        self.config_path = Path(config_path)
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from YAML file."""
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Configuration file not found: {self.config_path}\n"
                f"Copy config.yaml.example to config.yaml and configure it."
            )

        with open(self.config_path, "r") as f:
            self._yaml_config = yaml.safe_load(f)

        # Load environment-based configs
        self.immich = ImmichConfig()
        self.github_token = GitHubConfig().token

    @property
    def github_repo(self) -> str:
        """Get GitHub repository name."""
        return self._yaml_config["github"]["repo"]

    @property
    def github_branch(self) -> str:
        """Get GitHub branch name."""
        return self._yaml_config["github"].get("branch", "main")

    @property
    def commit_message_template(self) -> str:
        """Get commit message template."""
        return self._yaml_config["github"].get(
            "commit_message", "Add {count} photos from Immich tag '{tag}'"
        )

    @property
    def tag_mappings(self) -> Dict[str, str]:
        """Get tag to folder mappings."""
        return self._yaml_config["sync"]["tag_mappings"]

    @property
    def exclude_tags(self) -> List[str]:
        """Get excluded tags."""
        return self._yaml_config["sync"].get("exclude_tags", [])

    @property
    def filename_pattern(self) -> str:
        """Get filename pattern."""
        return self._yaml_config["sync"].get("filename_pattern", "{original}")

    @property
    def max_file_size_mb(self) -> Optional[int]:
        """Get maximum file size in MB."""
        return self._yaml_config["sync"].get("max_file_size_mb")

    @property
    def allowed_extensions(self) -> List[str]:
        """Get allowed file extensions."""
        return self._yaml_config["sync"].get(
            "allowed_extensions", [".jpg", ".jpeg", ".png", ".gif", ".webp"]
        )

    @property
    def automation_enabled(self) -> bool:
        """Check if automation is enabled."""
        return self._yaml_config.get("automation", {}).get("enabled", False)

    @property
    def automation_interval_minutes(self) -> int:
        """Get automation interval in minutes."""
        return self._yaml_config.get("automation", {}).get("interval_minutes", 60)

    @property
    def auto_sync_tags(self) -> List[str]:
        """Get tags to auto-sync."""
        return self._yaml_config.get("automation", {}).get("auto_sync_tags", [])

    @property
    def retry_on_failure(self) -> bool:
        """Check if retry on failure is enabled."""
        return self._yaml_config.get("automation", {}).get("retry_on_failure", True)

    @property
    def max_retries(self) -> int:
        """Get maximum retry attempts."""
        return self._yaml_config.get("automation", {}).get("max_retries", 3)

    @property
    def state_file_path(self) -> Path:
        """Get state file path."""
        return Path(
            self._yaml_config.get("state", {}).get("file_path", ".sync_state.json")
        )

    @property
    def state_backup_enabled(self) -> bool:
        """Check if state backup is enabled."""
        return self._yaml_config.get("state", {}).get("backup", True)

    @property
    def log_level(self) -> str:
        """Get log level."""
        return self._yaml_config.get("logging", {}).get("level", "INFO")

    @property
    def log_file(self) -> Optional[str]:
        """Get log file path."""
        return self._yaml_config.get("logging", {}).get("file")

    @property
    def rich_output(self) -> bool:
        """Check if rich terminal output is enabled."""
        return self._yaml_config.get("logging", {}).get("rich_output", True)
