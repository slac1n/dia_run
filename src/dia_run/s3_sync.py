import subprocess
from pathlib import Path
from shlex import join as shell_join

from loguru import logger

from dia_run.data_models.paths import DataPaths
from dia_run.settings import settings


class S3DataSync:
    def __init__(self, *, data_paths: DataPaths) -> None:
        self.data_paths = data_paths

    def sync_from_s3_on_startup(self) -> None:
        if not settings.s3_sync_enabled or not settings.s3_sync_on_startup or settings.use_mock_data:
            return
        self.sync_from_s3()

    def sync_to_s3_after_fetch(self) -> None:
        if not settings.s3_sync_enabled or not settings.s3_sync_after_fetch or settings.use_mock_data:
            return
        self.sync_to_s3(reason="fetch")

    def sync_to_s3_after_questionnaire(self) -> None:
        if not settings.s3_sync_enabled or not settings.s3_sync_after_questionnaire or settings.use_mock_data:
            return
        self.sync_to_s3(reason="questionnaire")

    def sync_from_s3(self) -> None:
        data_root = self._get_data_root()
        data_root.mkdir(parents=True, exist_ok=True)
        self._run_sync(source=self._get_s3_uri(), destination=str(data_root), direction="download")

    def sync_to_s3(self, *, reason: str) -> None:
        data_root = self._get_data_root()
        data_root.mkdir(parents=True, exist_ok=True)
        self._run_sync(source=str(data_root), destination=self._get_s3_uri(), direction=f"upload after {reason}")

    def _get_data_root(self) -> Path:
        if self.data_paths.data_root is None:
            msg = "S3 sync requires DataPaths created with DataPaths.from_root(...)"
            raise ValueError(msg)
        return self.data_paths.data_root

    def _get_s3_uri(self) -> str:
        if not settings.s3_bucket:
            msg = "S3 sync is enabled but S3_BUCKET is not configured"
            raise ValueError(msg)

        prefix = f"/{settings.s3_prefix}" if settings.s3_prefix else ""
        return f"s3://{settings.s3_bucket}{prefix}"

    def _run_sync(self, *, source: str, destination: str, direction: str) -> None:
        command = ["aws", "s3", "sync", source, destination, "--exclude", "*/.DS_Store"]
        if settings.aws_region:
            command.extend(["--region", settings.aws_region])

        logger.info("Running {} S3 sync: {}", direction, shell_join(command))
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            output = (result.stderr or result.stdout).strip()
            msg = f"S3 sync failed during {direction}: {output}"
            raise ValueError(msg)

        if result.stdout.strip():
            logger.info(result.stdout.strip())
