import subprocess
from unittest.mock import patch

import pytest

from dia_run.data_models.paths import DataPaths
from dia_run.s3_sync import S3DataSync
from dia_run.settings import AppSettings


class TestAppSettingsProductionFields:
    def test_production_settings_from_env(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "APP_ENV": "production",
                "DATA_ROOT": "/tmp/dia-run-data",
                "CARELINK_TOKEN_FILE": "/tmp/logindata.json",
                "STRAVA_REFRESH_TOKEN_FILE": "/tmp/strava-refresh-token.txt",
                "S3_SYNC_ENABLED": "true",
                "S3_BUCKET": "dia-run-bucket",
                "S3_PREFIX": "/prod/data/",
                "S3_SYNC_ON_STARTUP": "true",
                "S3_SYNC_AFTER_FETCH": "true",
                "S3_SYNC_AFTER_QUESTIONNAIRE": "true",
                "AWS_REGION": "eu-central-1",
            },
        ):
            settings = AppSettings()

        assert settings.is_production is True
        assert str(settings.data_root) == "/tmp/dia-run-data"
        assert str(settings.carelink_token_file) == "/tmp/logindata.json"
        assert str(settings.strava_refresh_token_file) == "/tmp/strava-refresh-token.txt"
        assert settings.s3_sync_enabled is True
        assert settings.s3_bucket == "dia-run-bucket"
        assert settings.s3_prefix == "prod/data"
        assert settings.s3_sync_on_startup is True
        assert settings.s3_sync_after_fetch is True
        assert settings.s3_sync_after_questionnaire is True
        assert settings.aws_region == "eu-central-1"

    def test_empty_refresh_token_file_becomes_none(self) -> None:
        with patch.dict("os.environ", {"STRAVA_REFRESH_TOKEN_FILE": ""}, clear=False):
            settings = AppSettings()
        assert settings.strava_refresh_token_file is None


class TestS3DataSync:
    def test_sync_from_s3_runs_expected_command(self, *, tmp_path_factory: pytest.TempPathFactory) -> None:
        data_paths = DataPaths.from_root(root=tmp_path_factory.mktemp("sync_download"))
        sync_service = S3DataSync(data_paths=data_paths)

        with (
            patch("dia_run.s3_sync.settings") as mock_settings,
            patch("subprocess.run") as mock_run,
        ):
            mock_settings.s3_sync_enabled = True
            mock_settings.s3_sync_on_startup = True
            mock_settings.use_mock_data = False
            mock_settings.s3_bucket = "dia-run-bucket"
            mock_settings.s3_prefix = "prod"
            mock_settings.aws_region = "eu-central-1"
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

            sync_service.sync_from_s3_on_startup()

        mock_run.assert_called_once_with(
            [
                "aws",
                "s3",
                "sync",
                "s3://dia-run-bucket/prod",
                str(data_paths.data_root),
                "--exclude",
                "*/.DS_Store",
                "--region",
                "eu-central-1",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_sync_to_s3_raises_when_bucket_missing(self, *, tmp_path_factory: pytest.TempPathFactory) -> None:
        data_paths = DataPaths.from_root(root=tmp_path_factory.mktemp("sync_upload"))
        sync_service = S3DataSync(data_paths=data_paths)

        with patch("dia_run.s3_sync.settings") as mock_settings:
            mock_settings.s3_sync_enabled = True
            mock_settings.s3_sync_after_fetch = True
            mock_settings.use_mock_data = False
            mock_settings.s3_bucket = None

            with pytest.raises(ValueError, match="S3_BUCKET"):
                sync_service.sync_to_s3_after_fetch()

    def test_sync_is_skipped_when_disabled(self, *, tmp_path_factory: pytest.TempPathFactory) -> None:
        data_paths = DataPaths.from_root(root=tmp_path_factory.mktemp("sync_disabled"))
        sync_service = S3DataSync(data_paths=data_paths)

        with (
            patch("dia_run.s3_sync.settings") as mock_settings,
            patch("subprocess.run") as mock_run,
        ):
            mock_settings.s3_sync_enabled = False
            mock_settings.s3_sync_after_questionnaire = True
            mock_settings.use_mock_data = False

            sync_service.sync_to_s3_after_questionnaire()

        mock_run.assert_not_called()
