import json
from pathlib import Path

import polars as pl
import questionary


class RunFuelQuestionnaire:
    def __init__(self, delta_table_path="data/strava/summary"):
        self.delta_table_path = delta_table_path
        self.activity_id = None
        self.responses = {}
        self.QUESTIONNAIRE_DIR = Path("data") / "run_questionnaires"
        self.QUESTIONNAIRE_DIR.mkdir(exist_ok=True)

    def load_filtered_activities(self):
        """Load activities, filtering out those that already have a JSON file."""
        # Read the delta table
        df = pl.scan_delta(self.delta_table_path).select(["activity_id", "name", "start_date_local"]).collect()

        # Filter out activities with existing JSON files
        existing_files = {int(f.stem) for f in self.QUESTIONNAIRE_DIR.glob("*.json")}
        df = df.filter(~df["activity_id"].is_in(existing_files))

        return df

    def ask_activity_id(self):
        """Ask for the activity ID based on name and date."""
        activities = self.load_filtered_activities()

        if activities.is_empty():
            print("No new activities to process. All activities have associated JSON files.")
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

    def ask_pre_run_info(self):
        """Ask for pre-run fueling information."""
        did_fuel = questionary.confirm("Did you take any carbohydrates before the run?").ask()

        if not did_fuel:
            self.responses["pre_run"] = []
            return

        carbs = questionary.text("How many grams of carbohydrates did you take pre-run?").ask()
        time_before_start = questionary.text(
            "How many minutes before the start of the run did you take it (use negative for before)?"
        ).ask()
        bolus_percentage = questionary.text("What percentage of bolus did you take?").ask()
        food_type = questionary.text("What kind of food was it?").ask()

        self.responses["pre_run"] = {
            "carbohydrates_g": carbs,
            "time_before_start_min": time_before_start,
            "bolus_percentage": bolus_percentage,
            "food_type": food_type,
        }

    def ask_bolus(self):
        """Ask for manual bolus information."""
        bolus_entries = []
        while True:
            did_bolus = questionary.confirm("Did you administer a manual bolus?").ask()

            if not did_bolus:
                break

            time_of_bolus = questionary.text(
                "When did you administer the bolus? (minutes from start, negative for before)"
            ).ask()
            bolus_units = questionary.text("How many units of bolus did you administer?").ask()

            bolus_entries.append(
                {
                    "time_of_bolus_min": time_of_bolus,
                    "bolus_units": bolus_units,
                }
            )

        self.responses["bolus"] = bolus_entries

    def ask_basal_adjustments(self):
        """Ask about basal adjustments before and during the run."""
        adjustments = []
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

            adjustment = {"type": adjustment_type}
            adjustment["start_time_min"] = questionary.text(
                f"When did you start {adjustment_type}? (minutes from start, negative for before)"
            ).ask()
            adjustment["end_time_min"] = questionary.text(
                f"When did you end {adjustment_type}? (minutes from start, negative for before)"
            ).ask()

            if adjustment_type == "Temporal Basalrate":
                adjustment["basal_rate_percentage"] = questionary.text(
                    "What was the set basal rate in percentage?"
                ).ask()

            adjustments.append(adjustment)

        self.responses["basal_adjustments"] = adjustments

    def ask_fueling_during_run(self):
        """Ask about fueling during the run."""
        fueling = []
        while True:
            took_fuel = questionary.confirm("Did you take carbohydrates during the run?").ask()

            if not took_fuel:
                break

            carb_amount = questionary.text("How many grams of carbohydrates did you take?").ask()
            time_during_run = questionary.text(
                "When during the run did you take it? (minutes from start, negative for before)"
            ).ask()
            food_type = questionary.text("What kind of food was it?").ask()

            fueling.append(
                {
                    "carbohydrates_g": carb_amount,
                    "time_during_run_min": time_during_run,
                    "food_type": food_type,
                }
            )

        self.responses["fueling_during_run"] = fueling

    def save_to_json(self):
        """Save responses to a JSON file."""
        output_file = self.QUESTIONNAIRE_DIR / f"{self.activity_id}.json"

        with open(output_file, "w") as f:
            json.dump(self.responses, f, indent=4)

        print(f"Questionnaire saved to {output_file}")

    def ask_me(self):
        """Run the entire questionnaire."""
        self.ask_activity_id()
        self.ask_pre_run_info()
        self.ask_basal_adjustments()
        self.ask_fueling_during_run()
        self.ask_bolus()
        self.save_to_json()


# Example usage:
if __name__ == "__main__":
    questionnaire = RunFuelQuestionnaire()
    questionnaire.ask_me()
