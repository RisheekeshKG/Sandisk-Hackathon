"""
github_client.py
Handles all GitHub API operations for VIGIL-AI:
  - Push user-uploaded files to inputs/
  - Read list of verification runs
  - Commit agent-generated results to verification_runs/run_XXX/
"""

import os
import base64
import json
import re
from datetime import datetime
from pathlib import Path

try:
    from github import Github, GithubException
    _HAS_PYGITHUB = True
except ImportError:
    _HAS_PYGITHUB = False


class GitHubClient:
    """
    Wraps PyGithub for VIGIL-AI operations.
    Requires a GitHub Personal Access Token (GITHUB_TOKEN env var).
    """

    def __init__(self, token: str | None = None):
        token = token or os.getenv("GITHUB_TOKEN", "")
        if not token:
            raise ValueError(
                "GitHub token missing. Set GITHUB_TOKEN in your .env file or environment.\n"
                "Create one at: https://github.com/settings/tokens (needs repo scope)"
            )
        if not _HAS_PYGITHUB:
            raise ImportError("PyGithub not installed. Run: pip install PyGithub")

        self._gh   = Github(token)
        
        # Dynamically determine the repository from the environment.
        # In GitHub Actions, GITHUB_REPOSITORY is set automatically.
        # When running locally, set it in your .env file as: GITHUB_REPOSITORY=owner/repo
        repo_name = os.getenv("GITHUB_REPOSITORY", "")
        if not repo_name:
            raise ValueError(
                "GITHUB_REPOSITORY environment variable is not set.\n"
                "  - In GitHub Actions: this is set automatically.\n"
                "  - Locally: add  GITHUB_REPOSITORY=<owner>/<repo>  to your .env file."
            )
            
        self._repo = self._gh.get_repo(repo_name)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _encode(self, content: str | bytes) -> str:
        if isinstance(content, str):
            content = content.encode("utf-8")
        return base64.b64encode(content).decode()

    def _file_exists(self, path: str) -> tuple[bool, str | None]:
        """Returns (exists, sha)."""
        try:
            f = self._repo.get_contents(path)
            if isinstance(f, list):
                f = f[0]
            return True, f.sha
        except Exception:
            return False, None

    def _put_file(self, repo_path: str, content: str | bytes, message: str):
        """Create or update a single file via the GitHub API.
        Retries once with a fresh SHA if a 409 conflict is returned."""
        exists, sha = self._file_exists(repo_path)
        for attempt in range(3):
            try:
                if exists and sha:
                    self._repo.update_file(repo_path, message, content, sha)
                else:
                    self._repo.create_file(repo_path, message, content)
                return  # success
            except GithubException as e:
                if e.status == 409 and attempt < 2:
                    # SHA stale — re-fetch and retry
                    exists, sha = self._file_exists(repo_path)
                    continue
                raise

    # ── Run numbering ──────────────────────────────────────────────────────────

    def _next_run_id(self) -> str:
        """Return the next run folder name, e.g. 'run_004'."""
        try:
            contents = self._repo.get_contents("verification_runs")
            if not isinstance(contents, list):
                contents = [contents]
            existing = [
                c.name for c in contents
                if c.type == "dir" and re.match(r"run_\d+", c.name)
            ]
        except Exception:
            existing = []

        if not existing:
            return "run_001"

        nums = [int(re.search(r"\d+", n).group()) for n in existing if re.search(r"\d+", n)]
        if not nums:
            return "run_001"
        return f"run_{max(nums) + 1:03d}"

    # ── Public API ─────────────────────────────────────────────────────────────

    def push_inputs(self, spec_bytes: bytes, spec_filename: str,
                    rtl_bytes: bytes,  rtl_filename: str) -> str:
        """
        Push uploaded spec + RTL to inputs/ and return the new run ID.
        The run ID is committed to inputs/current_run.txt so the CI
        agent knows which run to populate.
        """
        run_id = self._next_run_id()
        ts     = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        msg    = f"VIGIL-AI: Upload inputs for {run_id} [{ts}]"

        self._put_file(f"inputs/spec/{spec_filename}", spec_bytes, msg)
        self._put_file(f"inputs/rtl/{rtl_filename}",   rtl_bytes,  msg)

        # Persist run metadata so the CI job picks it up
        meta = json.dumps({
            "run_id":        run_id,
            "spec_filename": spec_filename,
            "rtl_filename":  rtl_filename,
            "uploaded_at":   ts,
        }, indent=2)
        self._put_file("inputs/current_run.json", meta, msg)

        return run_id

    def commit_results(self, run_id: str, files: dict[str, str | bytes]):
        """
        Commit agent-generated outputs to verification_runs/<run_id>/.
        `files` is a dict of {filename: content}.
        """
        base   = f"verification_runs/{run_id}"
        msg    = f"VIGIL-AI: Verification analysis results for {run_id}"

        for filename, content in files.items():
            self._put_file(f"{base}/{filename}", content, msg)

    def list_runs(self) -> list[dict]:
        """
        Return metadata for all completed runs, newest first.
        Reads verification_runs/<run_id>/report.json.
        """
        runs = []
        try:
            contents = self._repo.get_contents("verification_runs")
            if not isinstance(contents, list):
                contents = [contents]
        except Exception:
            return []

        for item in sorted(contents, key=lambda c: c.name, reverse=True):
            if item.type != "dir":
                continue
            try:
                rpt_file = self._repo.get_contents(
                    f"verification_runs/{item.name}/report.json"
                )
                if isinstance(rpt_file, list):
                    rpt_file = rpt_file[0]
                report = json.loads(rpt_file.decoded_content.decode())
            except Exception:
                report = {}

            runs.append({
                "run_id": item.name,
                "report": report,
            })

        return runs

    def get_run_file(self, run_id: str, filename: str) -> str | None:
        """Fetch the content of a file inside a run folder."""
        try:
            f = self._repo.get_contents(
                f"verification_runs/{run_id}/{filename}"
            )
            if isinstance(f, list):
                f = f[0]
            return f.decoded_content.decode("utf-8", errors="replace")
        except Exception:
            return None
