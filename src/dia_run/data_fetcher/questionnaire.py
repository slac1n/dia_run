import json
from pathlib import Path

import polars as pl
import questionary
from loguru import logger

from dia_run.data_models.paths import DataPaths
from dia_run.data_models.questionnaire import BasalAdjustment, BolusEntry, FuelingEntry, PreRunInfo, QuestionnaireModel


class RunFuelQuestionnaire:
    def __init__(self, data_paths: DataPaths):
        self.STRAVA_SUMMARY_DIR: Path = data_paths.strava_summary
        self.QUESTIONNAIRE_DIR: Path = data_paths.questionnaire
        self.QUESTIONNAIRE_DIR.mkdir(exist_ok=True)
        self.activity_id: int | None = None
        self.pre_run_info: list[PreRunInfo] = []
        self.basal_adjustments: list[BasalAdjustment] = []
        self.fueling_during_run: list[FuelingEntry] = []
        self.bolus: list[BolusEntry] = []

    def load_filtered_activities(self) -> pl.DataFrame:
        # Read the delta table
        df = pl.scan_delta(str(self.STRAVA_SUMMARY_DIR)).select(["activity_id", "name", "start_date_local"]).collect()

        # Filter out activities with existing JSON files
        existing_files = {int(f.stem) for f in self.QUESTIONNAIRE_DIR.glob("*.json")}
        df = df.filter(~df["activity_id"].is_in(existing_files))

        return df

    def ask_activity_id(self) -> None:
        activities = self.load_filtered_activities()

        if activities.is_empty():
            logger.info("No new activities to process. All activities have associated JSON files.")
            exit()

        # Prepare choices for the selection question
        choices = (
            activities.select(
                pl.format(
                    "{} ({})",  # Use positional placeholders
                    activities["name"],
                    activities["start_date_local"].dt.strftime("%Y-%m-%d %H:%M"),
                ).alias("formatted_choice")  # Alias the result for clarity
            )
            .to_series()
            .to_list()
        )

        selected = questionary.select("Select the activity for this questionnaire:", choices=choices).ask()

        # Map the selection back to the activity_id
        self.activity_id = activities.filter(
            pl.format(
                "{} ({})",  # Use positional placeholders
                activities["name"],
                activities["start_date_local"].dt.strftime("%Y-%m-%d %H:%M"),
            )
            == selected
        )["activity_id"].item()

    def ask_pre_run_info(self) -> None:
        did_fuel = questionary.confirm("Did you take any carbohydrates before the run?").ask()

        if not did_fuel:
            return

        carbs = questionary.text("How many grams of carbohydrates did you take pre-run?").ask()
        time_before_start = questionary.text(
            "How many minutes before the start of the run did you take it (use negative for before)?"
        ).ask()
        bolus_percentage = questionary.text("What percentage of bolus did you take?").ask()
        food_type = questionary.text("What kind of food was it?").ask()

        self.pre_run_info.append(
            PreRunInfo(
                carbohydrates_g=int(carbs),
                time_before_start_min=int(time_before_start),
                bolus_percentage=float(bolus_percentage),
                food_type=food_type,
            )
        )

    def ask_bolus(self) -> None:
        while True:
            did_bolus = questionary.confirm("Did you administer a manual bolus?").ask()

            if not did_bolus:
                break

            time_of_bolus = questionary.text(
                "When did you administer the bolus? (minutes from start, negative for before)"
            ).ask()
            bolus_units = questionary.text("How many units of bolus did you administer?").ask()

            self.bolus.append(
                BolusEntry(
                    time_of_bolus_min=int(time_of_bolus),
                    bolus_units=float(bolus_units),
                )
            )

    def ask_basal_adjustments(self) -> None:
        while True:
            adjustment_type = questionary.select(
                "Did you adjust your basal rates?",
                choices=[
                    "Temporal SmartGuard",
                    "Temporal Basalrate",
                    "Stop Pump",
                    "No [More] Adjustments",
                ],
            ).ask()

            if adjustment_type == "No [More] Adjustments":
                break

            start_time_min = int(
                questionary.text(
                    f"When did you start {adjustment_type}? (minutes from start, negative for before)"
                ).ask()
            )
            end_time_min = int(
                questionary.text(f"When did you end {adjustment_type}? (minutes from start, negative for before)").ask()
            )

            basal_rate_percentage = None
            if adjustment_type == "Temporal Basalrate":
                basal_rate_percentage = float(questionary.text("What was the set basal rate in percentage?").ask())

            self.basal_adjustments.append(
                BasalAdjustment(
                    type=adjustment_type,
                    start_time_min=start_time_min,
                    end_time_min=end_time_min,
                    basal_rate_percentage=basal_rate_percentage,
                )
            )

    def ask_fueling_during_run(self) -> None:
        while True:
            took_fuel = questionary.confirm("Did you take carbohydrates during the run?").ask()

            if not took_fuel:
                break

            carb_amount = int(questionary.text("How many grams of carbohydrates did you take?").ask())
            time_during_run = int(
                questionary.text("When during the run did you take it? (minutes from start, negative for before)").ask()
            )
            food_type = questionary.text("What kind of food was it?").ask()

            self.fueling_during_run.append(
                FuelingEntry(
                    carbohydrates_g=carb_amount,
                    time_during_run_min=time_during_run,
                    food_type=food_type,
                )
            )

    def save_to_json(self) -> None:
        output_file = self.QUESTIONNAIRE_DIR / f"{self.activity_id}.json"

        questionnaire_data = QuestionnaireModel(
            pre_run=self.pre_run_info,
            basal_adjustments=self.basal_adjustments,
            fueling_during_run=self.fueling_during_run,
            bolus=self.bolus,
        )

        with open(output_file, "w") as f:
            json.dump(questionnaire_data.model_dump(mode="json"), f, indent=4)

        logger.info(f"Questionnaire saved to {output_file}")

    def ask_me(self) -> None:
        self.ask_activity_id()
        self.ask_pre_run_info()
        self.ask_basal_adjustments()
        self.ask_fueling_during_run()
        self.ask_bolus()
        self.save_to_json()
