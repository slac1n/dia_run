from dia_run.data_fetcher.live_fetcher import LiveDataFetcher
from dia_run.data_fetcher.questionnaire import RunFuelQuestionnaire
from dia_run.data_models.paths import DataPaths

# Backward-compatible alias
DataFetcher = LiveDataFetcher


def run_fetcher() -> None:
    data_paths = DataPaths()
    data_fetcher = DataFetcher(data_paths=data_paths)
    data_fetcher.fetch_latest_data_and_save()

    questionnaire = RunFuelQuestionnaire(data_paths=data_paths)
    questionnaire.ask_me()
