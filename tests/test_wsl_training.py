from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from ticketing.config import Settings
from ticketing.training import Trainer
from ticketing.wsl_soup import CANCEL


class WslTrainingTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_uses_distribution_and_linux_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(root, "unused", False, "/home/trainer/bin/soup", {}, "Ubuntu-24.04")
            trainer = Trainer(settings)
            process = AsyncMock()
            process.wait.return_value = 0
            with patch("ticketing.training.asyncio.create_subprocess_exec", return_value=process) as spawn:
                await trainer.command(root, settings.soup, "train", "--config", "soup.yaml")
            self.assertEqual(spawn.call_args.args, (
                "wsl.exe", "--distribution", "Ubuntu-24.04", "--cd", str(root),
                "--exec", "/usr/bin/python3", ".soup-wsl.py", settings.soup,
                "train", "--config", "soup.yaml",
            ))
            self.assertTrue((root / ".soup-wsl.py").is_file())

    async def test_cancellation_is_forwarded_to_linux_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(root, "unused", False, "/home/trainer/bin/soup", {}, "Ubuntu-24.04")
            trainer = Trainer(settings)
            process = AsyncMock()
            process.wait.return_value = 130
            with patch.object(trainer, "stop_process") as native_stop:
                await trainer.stop_job_process(root, process)
            self.assertTrue((root / CANCEL).exists())
            native_stop.assert_not_called()
