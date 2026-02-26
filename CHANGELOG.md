## v0.18.0 (2026-02-26)

### Feat

- **TG-24**: add point-count TIR calculation for basal adjustments (#37)

## v0.17.0 (2026-02-25)

### Feat

- add Race run type with marathon/halbmarathon detection (#36)

## v0.16.1 (2026-02-25)

### Fix

- **web**: improve fetch flow and questionnaire integration (#35)

## v0.16.0 (2026-02-24)

### Feat

- replace Streamlit dashboard with FastAPI web app (#34)

## v0.15.0 (2026-02-23)

### Feat

- add taiga login and auto-refresh, fix skill workflow (#33)

## v0.14.1 (2026-02-23)

### Fix

- add BG_READING marker type support (#32)

## v0.14.0 (2026-02-23)

### Feat

- add bolus percentage vs in-going glucose scatter chart (#31)

## v0.13.0 (2026-02-22)

### Feat

- add Pydantic and Pandera validation to data fetcher (#30)

## v0.12.2 (2026-02-22)

### Fix

- prevent double execution with correct if statement (#29)

## v0.12.1 (2026-02-22)

### Fix

- prevent double execution of commitizen bump workflow (#28)

## v0.12.0 (2026-02-21)

### Feat

- **TG-6**: visualize fueling impact on sensor glucose levels (#27)

## v0.11.0 (2026-02-21)

### Feat

- add Taiga integration with OpenCode /taiga command (#26)

## v0.10.1 (2026-02-21)

### Fix

- update vendored CareLink client for new Medtronic Auth0 workflow (#24)

## v0.10.0 (2026-02-21)

### Feat

- **TG-7**: visualize pre-nutrition impact on in-going sensor glucose (#23)

### Fix

- use PAT_TOKEN instead of GITHUB_TOKEN in bumpversion workflow (#25)

## v0.9.0 (2026-02-17)

### Feat

- **TG-14**: add CI workflow for pytest execution (#22)

## v0.8.0 (2026-02-17)

### Feat

- **TG-17**: add pre-commit hooks for ruff and mypy (#21)

## v0.7.0 (2026-02-17)

### Feat

- **TG-23**: Visualize 30 days average KPIs (#20)

## v0.6.1 (2025-06-18)

### Fix

- make insulin_on_board_in_going nullable (#16)

## v0.6.0 (2025-04-19)

### Feat

- **TG-9**: Implement proper data validation for data processing (#15)

## v0.5.3 (2025-03-31)

### Fix

- add datetime to heartrate streams (#13)

## v0.5.2 (2025-03-30)

### Fix

- Filter specific carelink data types (#12)

## v0.5.1 (2025-03-30)

### Fix

- Remove unused activity id column (#11)

## v0.5.0 (2025-03-27)

### Feat

- Implement running activity calender (#7)

## v0.4.0 (2025-03-20)

### Feat

- display relation between glucose behavior and insulin on board (#5)

## v0.3.0 (2025-03-19)

### Feat

- Calculate insulin on board at start (#4)

## v0.2.0 (2025-03-18)

### Feat

- visualize strave stream time series data overlayed on top of glucose
- update dashboard with carelink plots and nutrition information
- pace to table
- first dashboard with activity table overview which includes first, last, and avg. sensor glucose reading
- retrieve kilojoules from strava summary
- ask questions about the fueling of the run
- strave data split in summary and streams, plus addtional streams
- check if delta table exisits

### Fix

- wrong branch specified for github actions
- replace wrong 0 cmg values with None
