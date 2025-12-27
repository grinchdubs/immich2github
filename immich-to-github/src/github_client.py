"""GitHub API client for uploading files to repositories."""

import base64
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from github import Github, Repository, GithubException
from rich.console import Console

console = Console()


class GitHubClient:
    """Client for interacting with GitHub API."""

    def __init__(self, token: str, repo_name: str, branch: str = "main"):
        """Initialize GitHub client.

        Args:
            token: GitHub personal access token
            repo_name: Repository name in format "username/repo"
            branch: Branch name (default: "main")
        """
        self.github = Github(token)
        self.repo_name = repo_name
        self.branch = branch
        self._repo: Optional[Repository.Repository] = None

    @property
    def repo(self) -> Repository.Repository:
        """Get repository object (lazy loaded)."""
        if self._repo is None:
            try:
                self._repo = self.github.get_repo(self.repo_name)
            except GithubException as e:
                console.print(f"[red]Error accessing repository {self.repo_name}: {e}[/red]")
                raise
        return self._repo

    def upload_file(
        self,
        file_path: Path,
        github_path: str,
        commit_message: str,
        overwrite: bool = False,
    ) -> str:
        """Upload a file to GitHub repository.

        Args:
            file_path: Local path to the file
            github_path: Path in the GitHub repository
            commit_message: Commit message
            overwrite: Whether to overwrite existing file

        Returns:
            URL of the uploaded file (raw GitHub content URL)

        Raises:
            FileExistsError: If file exists and overwrite is False
            GithubException: If upload fails
        """
        try:
            # Read file content
            with open(file_path, "rb") as f:
                content = f.read()

            # Check if file already exists
            try:
                existing_file = self.repo.get_contents(github_path, ref=self.branch)
                if not overwrite:
                    raise FileExistsError(
                        f"File {github_path} already exists. Use overwrite=True to replace."
                    )
                # Update existing file
                self.repo.update_file(
                    path=github_path,
                    message=commit_message,
                    content=content,
                    sha=existing_file.sha,
                    branch=self.branch,
                )
                console.print(f"[green]Updated:[/green] {github_path}")
            except GithubException as e:
                if e.status == 404:
                    # File doesn't exist, create it
                    self.repo.create_file(
                        path=github_path,
                        message=commit_message,
                        content=content,
                        branch=self.branch,
                    )
                    console.print(f"[green]Created:[/green] {github_path}")
                else:
                    raise

            # Return raw GitHub URL
            return f"https://raw.githubusercontent.com/{self.repo_name}/{self.branch}/{github_path}"

        except Exception as e:
            console.print(f"[red]Error uploading {file_path} to {github_path}: {e}[/red]")
            raise

    def upload_files_batch(
        self,
        files: List[tuple[Path, str]],
        commit_message: str,
    ) -> List[str]:
        """Upload multiple files in individual commits.

        Args:
            files: List of tuples (local_path, github_path)
            commit_message: Base commit message (will be customized per file)

        Returns:
            List of URLs for uploaded files
        """
        urls = []
        for local_path, github_path in files:
            try:
                msg = f"{commit_message}: {github_path}"
                url = self.upload_file(local_path, github_path, msg)
                urls.append(url)
            except Exception as e:
                console.print(f"[yellow]Skipped {local_path}: {e}[/yellow]")
                continue
        return urls

    def file_exists(self, github_path: str) -> bool:
        """Check if a file exists in the repository.

        Args:
            github_path: Path in the GitHub repository

        Returns:
            True if file exists, False otherwise
        """
        try:
            self.repo.get_contents(github_path, ref=self.branch)
            return True
        except GithubException as e:
            if e.status == 404:
                return False
            raise

    def get_file_sha(self, github_path: str) -> Optional[str]:
        """Get SHA hash of a file in the repository.

        Args:
            github_path: Path in the GitHub repository

        Returns:
            SHA hash if file exists, None otherwise
        """
        try:
            content = self.repo.get_contents(github_path, ref=self.branch)
            return content.sha
        except GithubException as e:
            if e.status == 404:
                return None
            raise

    def list_directory(self, directory_path: str = "") -> List[str]:
        """List files in a directory.

        Args:
            directory_path: Path to directory in repository

        Returns:
            List of file paths
        """
        try:
            contents = self.repo.get_contents(directory_path, ref=self.branch)
            if isinstance(contents, list):
                return [item.path for item in contents]
            return [contents.path]
        except GithubException as e:
            if e.status == 404:
                return []
            raise

    def test_connection(self) -> bool:
        """Test connection to GitHub repository.

        Returns:
            True if connection is successful, False otherwise
        """
        try:
            # Try to get repository info
            _ = self.repo.name
            return True
        except Exception as e:
            console.print(f"[red]GitHub connection test failed: {e}[/red]")
            return False

    def get_raw_url(self, github_path: str) -> str:
        """Get raw GitHub URL for a file.

        Args:
            github_path: Path in the GitHub repository

        Returns:
            Raw GitHub content URL
        """
        return f"https://raw.githubusercontent.com/{self.repo_name}/{self.branch}/{github_path}"
