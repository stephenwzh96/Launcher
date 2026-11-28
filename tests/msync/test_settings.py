from pathlib import Path

from machine_sync.settings import syncthing_folders
from msync.helpers import TempDirCase

CONFIG = """<configuration version="37">
    <folder id="tripsync-data" label="TripSync" path="{home}\\TripSync" type="sendonly"></folder>
    <folder id="ibkr-settlements" label="settlements" path="{home}\\IBKR\\data\\settlements" type="receiveonly"></folder>
    <folder id="default" label="Default Folder" path="~\\Sync" type="sendreceive"></folder>
</configuration>
"""


class SyncthingFoldersTest(TempDirCase):
    def test_folders_read_from_this_pcs_syncthing_config(self) -> None:
        cfg = self.tmp / "TripSync_syncthing" / "config.xml"
        cfg.parent.mkdir()
        cfg.write_text(CONFIG.format(home=self.tmp))
        folders = syncthing_folders(self.tmp, localappdata=None)
        self.assertIn((self.tmp / "IBKR" / "data" / "settlements").resolve(), folders)
        self.assertIn((self.tmp / "Sync").resolve(), folders)  # "~" is this user's home

    def test_no_config_no_folders(self) -> None:
        self.assertEqual(syncthing_folders(self.tmp, localappdata=self.tmp / "nowhere"), ())

    def test_unreadable_config_is_ignored(self) -> None:
        cfg = self.tmp / "TripSync_syncthing" / "config.xml"
        cfg.parent.mkdir()
        cfg.write_text("<not xml")
        self.assertEqual(syncthing_folders(self.tmp, localappdata=None), ())


class ReposTest(TempDirCase):
    def test_trend_v1_is_its_own_repo_beside_trend(self) -> None:
        """Stephen, 28 Nov 2026: Trend_v1 (a worktree of Trend on feat/macro-v1) synced on all three PCs. A path in
        it belongs to Trend_v1, never to Trend, and Trend's paths stay Trend's."""
        from machine_sync.data_sync import _repo_of
        from machine_sync.settings import DEFAULT_REPOS, Settings

        self.assertIn("Trend_v1", DEFAULT_REPOS)
        self.assertEqual(len(DEFAULT_REPOS), len(set(DEFAULT_REPOS)))
        cfg = Settings(home=self.tmp, machine="desktop")
        self.assertEqual(_repo_of(cfg, "Trend_v1/AIJPMT1A_build/x.json"), "Trend_v1")
        self.assertEqual(_repo_of(cfg, "Trend/AIJPMT1A_build/x.json"), "Trend")
        self.assertIsNone(_repo_of(cfg, "Trend_v2/x.json"))


class MarcoSynegyTest(TempDirCase):
    def test_marcosynegy_is_synced_without_its_venv_git_or_credentials(self) -> None:
        """Stephen, 28 Nov 2026: the MarcoSynegy folder synced on all three PCs. Its data and notebooks go; its .venv,
        the nested repos' .git folders and the DataQuery credentials file (JPMQS.txt) never leave the PC."""
        from machine_sync.data_files import data_files
        from machine_sync.settings import DEFAULT_PLAIN_ROOTS, Settings

        self.assertEqual(DEFAULT_PLAIN_ROOTS["MarcoSynegy"], [])
        root = self.tmp / "MarcoSynegy"
        for rel in ("README.md", "JPMQS.txt", "data/jpmaqs/x.parquet", "notebooks/a.ipynb", ".venv/Lib/site.py",
                    "shadow/.git/HEAD", "shadow/run_day.py"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("x")
        cfg = Settings(home=self.tmp, machine="desktop", repos=())
        found = set(data_files(cfg))
        self.assertEqual(found, {f"MarcoSynegy/{r}" for r in ("README.md", "data/jpmaqs/x.parquet",
                                                              "notebooks/a.ipynb", "shadow/run_day.py")})
