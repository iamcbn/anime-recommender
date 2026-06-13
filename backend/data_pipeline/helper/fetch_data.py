from __future__ import annotations
import json
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional
import kaggle

KAGGLE_DATASET = 'calebmwelsh/anilist-anime-dataset'

class KaggleDataVersionManager:
    """
    Manage local versioned data artefacts for a Kaggle dataset.

    Policy:
      - One local version directory per Kaggle dataset version
      - Local version name: v{dataset_version}
      - New version directory is created only if remote version is newer
    """

    STATE_FILE = ".dataset_state.json"

    def __init__(self, data_dir: str, dataset_ref: str):
        self.data_dir = Path(data_dir).resolve()
        self.dataset_ref = dataset_ref

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.data_dir / self.STATE_FILE
        self._load_state()

    # ----------------------
    # STATE HANDLING
    # ----------------------
    def _load_state(self):
        if self.state_file.exists():
            self.state = json.loads(self.state_file.read_text())
        else:
            self.state = {}

    def _save_state(self):
        self.state_file.write_text(json.dumps(self.state, indent=2))

    def last_local_version(self) -> Optional[int]:
        return self.state.get("kaggle_version")
    
    def last_state_version(self) -> Optional[int]:
        return self.state.get("state_version")

    def _record_version(self, version):
        self.state["kaggle_version"] = version
        self.state["updated_at"] = datetime.now(UTC).isoformat().split("+")[0] + "Z"
        if "state_version" not in self.state:
            self.state["state_version"] = 1
        else:
            self.state["state_version"] += 1
        self._save_state()
        self._load_state()  # 🔑 refresh in-memory state

    # ----------------------
    # KAGGLE VERSION LOOKUP
    # ----------------------

    def get_remote_dataset_version(self) -> Optional[int]:
        """
        Retrieve Kaggle dataset version via API.
        No download involved.
        """

        #kaggle.api.authenticate()
        metadata = kaggle.api.dataset_list_files(self.dataset_ref)
        if not metadata.dataset_files:
            return None

        # Assuming the first file's creation date indicates dataset version
        return int(metadata.dataset_files[2].creation_date.timestamp())
    

    # ----------------------
    ###  VERSION DIRECTORY LOGIC
    # ----------------------
    def version_dir(self, version: int) -> Path:
        return self.data_dir / f"v{version}"

    def create_version_dir(self, version: int) -> Path:
        path = self.version_dir(version)
        path.mkdir(parents=True, exist_ok=True)

        (path / "raw_data").mkdir(exist_ok=True)
        (path / "metadata").mkdir(exist_ok=True)

        meta = {
            "kaggle_dataset_ref": self.dataset_ref,
            "kaggle_version": version,
            "created_at": datetime.now(UTC).isoformat().split("+")[0] + "Z",
        }
        (path / "metadata" / "metadata.json").write_text(json.dumps(meta, indent=2))
        kaggle.api.dataset_metadata("calebmwelsh/anilist-anime-dataset", path=(path / "metadata"))

        return path

    # ----------------------
    # Public API
    # ----------------------
    def check_and_prepare(self, db_kaggle_version: Optional[int] = None) -> tuple[Optional[Path], bool, int]:
        """
        Check remote dataset version and create local artefact dir if new.

        Args:
            db_kaggle_version: The kaggle_version stored in the database.
                               Used as the primary staleness check. Falls back
                               to the local JSON file when None (legacy rows / first run).

        Returns:
            (path, created, remote_version)
        """
        remote_version = self.get_remote_dataset_version()
        if remote_version is None:
            raise RuntimeError("Could not determine remote Kaggle dataset version")

        # Primary check: database's kaggle_version (persists across CI runs)
        # Fallback: local JSON file's kaggle_version (only works when filesystem persists)
        known_version = db_kaggle_version or self.last_local_version()
        state_version = self.last_state_version()


        if known_version is None or remote_version > known_version:
            if state_version is None:
                path = self.create_version_dir(1) 
            else:
                path = self.create_version_dir(state_version + 1)

            #self._record_version(remote_version)
            return path, True, remote_version

        return None, False, remote_version


