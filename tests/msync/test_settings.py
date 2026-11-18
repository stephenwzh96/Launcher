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
