"""Small repo-local temporary directories for Windows fixture tests."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path


class WorkspaceTemporaryDirectory:
    def __init__(self, owner_file: str):
        self.repo_root = Path(__file__).resolve().parents[1]
        if not Path(owner_file).resolve().is_relative_to(self.repo_root):
            raise ValueError("Fixture owner must be inside the helper's repository")
        self.path = self.repo_root / f".fixture-{uuid.uuid4().hex}"
        self.path.mkdir()
        self.name = str(self.path)

    def cleanup(self):
        resolved = self.path.resolve(strict=True)
        if resolved.parent != self.repo_root or not resolved.name.startswith(".fixture-"):
            raise RuntimeError(f"Refusing fixture cleanup outside its workspace: {resolved}")
        shutil.rmtree(resolved)

    def __enter__(self):
        return self.name

    def __exit__(self, *_):
        self.cleanup()


def workspace_tempdir(owner_file: str) -> WorkspaceTemporaryDirectory:
    return WorkspaceTemporaryDirectory(owner_file)
