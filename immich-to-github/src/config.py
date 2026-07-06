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


class GitPushConfig(BaseSettings):
    """Git remote push credentials.

    The token authenticates pushes to the git remote (Gitea now, GitHub
    later). Kept out of config.yaml so the tracked config stays secret-free.
    """

    token: str = Field(..., validation_alias="GIT_PUSH_TOKEN")

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
        self.git_token = GitPushConfig().token

    @property
    def _git(self) -> Dict:
        """Get the git remote config block."""
        return self._yaml_config.get("git", {})

    @property
    def git_remote_host(self) -> str:
        """Host[:port] of the git remote, e.g. 'grnchnas:30008'."""
        return self._git["remote_host"]

    @property
    def git_remote_path(self) -> str:
        """Repo path on the remote, e.g. 'grinchdubs/grnch.xyz_photos.git'."""
        return self._git["remote_path"]

    @property
    def git_branch(self) -> str:
        """Branch to push photos to."""
        return self._git.get("branch", "main")

    @property
    def git_work_dir(self) -> str:
        """Local path for the working clone (persist on the /data volume)."""
        return self._git.get("work_dir", "/data/repo")

    @property
    def git_author_name(self) -> str:
        """Commit author name."""
        return self._git.get("author_name", "immich-sync")

    @property
    def git_author_email(self) -> str:
        """Commit author email."""
        return self._git.get("author_email", "immich-sync@grnch.xyz")

    @property
    def git_username(self) -> str:
        """Basic-auth username paired with GIT_PUSH_TOKEN."""
        return self._git.get("username", "oauth2")

    @property
    def git_use_https(self) -> bool:
        """Whether the git remote uses https:// (default http://)."""
        return self._git.get("use_https", False)

    @property
    def git_remote_display(self) -> str:
        """Credential-free remote string for logging/banners."""
        scheme = "https" if self.git_use_https else "http"
        return f"{scheme}://{self.git_remote_host}/{self.git_remote_path}"

    @property
    def commit_message_template(self) -> str:
        """Get commit message template."""
        return self._yaml_config.get("github", {}).get(
            "commit_message", "Add {count} photos from Immich tag '{tag}'"
        )

    @property
    def tag_mappings(self) -> Dict[str, str]:
        """Get tag to folder mappings."""
        return self._yaml_config["sync"].get("tag_mappings", {})

    @property
    def album_mappings(self) -> Dict[str, str]:
        """Get album to folder mappings."""
        return self._yaml_config["sync"].get("album_mappings", {})

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
            "allowed_extensions", [".jpg", ".jpeg", ".png"]
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
    def auto_sync_albums(self) -> List[str]:
        """Get albums to auto-sync (matched by album name)."""
        return self._yaml_config.get("automation", {}).get("auto_sync_albums", [])

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
