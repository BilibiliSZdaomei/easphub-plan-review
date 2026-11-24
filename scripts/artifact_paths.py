"""Resolve disposable test/build paths outside source and synced folders; no writes."""
import hashlib
import os
from pathlib import Path

APP_ID = "plan-review"

def artifact_root(project_root, app_id=None):
    project = Path(project_root).resolve()
    configured = os.environ.get("CODEX_ARTIFACT_ROOT")
    if configured:
        base = Path(configured).expanduser()
        if not base.is_absolute():
            raise ValueError("CODEX_ARTIFACT_ROOT must be an absolute path outside synced folders")
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "CodexArtifacts"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "codex-artifacts"
    if not base.is_absolute():
        raise ValueError("Artifact cache base must be an absolute path")
    identity = hashlib.sha256(os.path.normcase(str(project)).encode()).hexdigest()[:12]
    candidate = base / ((app_id or APP_ID) + "-" + identity) / "adaptation"
    resolved = candidate.resolve()
    if resolved == project or project in resolved.parents:
        raise ValueError("Artifact destination must be outside the source project")
    for target in (candidate.absolute(), resolved):
        if any((ancestor / ".obsidian").exists() for ancestor in (target, *target.parents)):
            raise ValueError("Artifact destination must be outside the entire Obsidian vault")
    known = [os.environ.get(k) for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")]
    for folder in filter(None, known):
        sync_root = Path(folder).resolve()
        if resolved == sync_root or sync_root in resolved.parents:
            raise ValueError("Artifact destination must be outside synced folders")
    return resolved

if __name__ == "__main__":
    print(artifact_root(Path(__file__).resolve().parents[1]))
