import requests
import stat
import zipfile
import logging
import io
from tqdm import tqdm
import os
import shutil # to remove folder
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# ─────────────────────────── helpers ────────────────────────────

def _force_remove(action, name, exc):
    """onerror callback: force-delete read-only files on Windows."""
    try:
        os.chmod(name, stat.S_IWRITE)
        os.remove(name)
    except Exception as e:
        logger.warning(f"Could not remove '{name}': {e}")


def delete_dir(path_) -> None:
    """Recursively delete a directory, handling read-only files."""
    path = Path(path_)
    if path.exists():
        shutil.rmtree(path, onerror=_force_remove)
        logger.info(f"Deleted existing directory: {path}")


def repo_name_from_url(url: str) -> str:
    """Extract a clean repo name from a GitHub URL."""
    # Strip trailing slash / .git suffix
    clean = url.rstrip("/").removesuffix(".git")
    return clean.split("/")[-1]


# ─────────────────────────── core ───────────────────────────────

def download_github_repo(
    repo_url: str,
    storage_dir: Path,
    *,
    timeout: int = 30,
    chunk_size: int = 1024,
    overwrite: bool = True,
) -> Path:
    """
    Download a GitHub repository as a ZIP and extract it into *storage_dir*.

    Parameters
    ----------
    repo_url    : Full GitHub repo URL, e.g. "https://github.com/user/repo"
    storage_dir : Parent folder that holds all downloaded repos.
    timeout     : Seconds before the HTTP connection times out.
    chunk_size  : Download chunk size in bytes.
    overwrite   : If True, delete an existing copy before re-downloading.

    Returns
    -------
    Path to the extracted repository directory inside storage_dir.

    Raises
    ------
    ValueError      : Bad URL or missing repo name.
    requests.HTTPError : Non-200 response from GitHub.
    zipfile.BadZipFile : Corrupted/incomplete download.
    OSError         : Filesystem failures.
    """

    # ── validate URL ──────────────────────────────────────────────
    # Strip URL fragments (#), then whitespace, then trailing slashes
    repo_url = repo_url.split('#')[0].strip().rstrip("/")
    if not repo_url.startswith("https://github.com/"):
        raise ValueError(f"Expected a GitHub URL, got: {repo_url!r}")

    name = repo_name_from_url(repo_url)
    if not name:
        raise ValueError(f"Could not extract a repo name from URL: {repo_url!r}")

    # ── prepare destination ───────────────────────────────────────
    storage_dir.mkdir(parents=True, exist_ok=True)
    repo_dest = storage_dir / name

    if repo_dest.exists():
        if overwrite:
            delete_dir(repo_dest)
        else:
            logger.info(f"Repo already exists and overwrite=False: {repo_dest}")
            return repo_dest

    # ── download ──────────────────────────────────────────────────
    zip_url = f"{repo_url}/zipball/HEAD"
    logger.info(f"Connecting to GitHub: {zip_url}")

    try:
        response = requests.get(
            zip_url,
            stream=True,
            timeout=timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.exceptions.Timeout:
        raise requests.exceptions.Timeout(
            f"Connection timed out after {timeout}s — check your network."
        )
    except requests.exceptions.ConnectionError as e:
        raise requests.exceptions.ConnectionError(
            f"Could not reach GitHub. Is the URL correct? Details: {e}"
        )

    total_size = int(response.headers.get("content-length", 0))

    file_stream = io.BytesIO()
    with tqdm(
        total=total_size or None,
        unit="iB",
        unit_scale=True,
        desc=f"Downloading '{name}'",
    ) as bar:
        for chunk in response.iter_content(chunk_size):
            if chunk:                   # filter keep-alive empty chunks
                file_stream.write(chunk)
                bar.update(len(chunk))

    downloaded_bytes = file_stream.tell()
    if downloaded_bytes == 0:
        raise ValueError("Download produced an empty file — nothing to extract.")

    logger.info(f"Download complete ({downloaded_bytes / 1024:.1f} KB). Extracting…")

    # ── validate zip ──────────────────────────────────────────────
    file_stream.seek(0)
    if not zipfile.is_zipfile(file_stream):
        raise zipfile.BadZipFile("Downloaded content is not a valid ZIP archive.")

    # ── extract ───────────────────────────────────────────────────
    file_stream.seek(0)
    repo_dest.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(file_stream) as z:
        members = z.namelist()
        if not members:
            raise zipfile.BadZipFile("ZIP archive is empty.")

        # GitHub wraps everything in a top-level folder like "user-repo-abc123/"
        # Detect it so we can strip it and land files directly in repo_dest.
        top_level = members[0].split("/")[0] + "/"

        with tqdm(total=len(members), unit="file", desc="Extracting") as bar:
            for member in members:
                # Strip the GitHub-generated prefix
                relative = member[len(top_level):] if member.startswith(top_level) else member
                if not relative:          # skip the top-level dir entry itself
                    bar.update(1)
                    continue

                target = repo_dest / relative

                if member.endswith("/"):  # directory entry
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(member) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)

                bar.update(1)

    logger.info(f"[SUCCESS] Repository extracted to: {repo_dest}")
    return repo_dest
