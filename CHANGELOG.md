## v0.33.0 (2026-10-23)

### Feat

- add conversational running coach with contextual memory

## v0.32.1 (2026-10-17)

### Docs

- Refresh README with a concise project overview, setup instructions, and a synthetic-data app screenshot.

## v0.32.0 (2026-10-16)

### Feat

- allow additional questionnaire entries for long runs

## v0.31.0 (2026-04-22)

### Feat

- add AI run recommendations on activity detail page

## v0.30.0 (2026-04-21)

### Feat

- wire fueling timing/SG charts and relocate basal lead-time card
- relabel pattern charts and add fueling timing/SG charts
- add fueling timing and SG aggregators
- wire pattern insights section into dashboard
- add pattern insights chart module
- add pattern insights aggregator methods
- add pattern features table and schemas

### Fix

- move n= counts into x-axis labels on grouped bar charts

### Refactor

- rename peak_in_range to peak_no_spike
- split pattern features into per-analysis helpers

## v0.29.0 (2026-04-15)

### Feat

- overhaul dashboard UI layout and navigation

## v0.28.1 (2026-04-15)

### Fix

- disable SSL verification in vendored CareLink client

## v0.28.0 (2026-04-14)

### Feat

- add nightly CareLink heartbeat to keep token alive and alert on failures

### Fix

- resolve supercronic PID 1 crash by disabling process reaper
- fix supercronic exec error and arch detection in crontab and Dockerfile

## v0.27.0 (2026-04-13)

### Feat

- show avg glucose and TIR on activity detail and overview (TG-43)

## v0.26.3 (2026-04-11)

### Fix

- allow CareLink SG entries without timestamp

## v0.26.2 (2026-03-22)

### Fix

- accept CareLink CALIBRATION markers

## v0.26.1 (2026-03-14)

### Fix

- tolerate missing Strava metrics for indoor runs

## v0.26.0 (2026-03-14)

### Feat

- **TG-42**: abort stale CareLink fetches before saving (#58)

## v0.25.0 (2026-03-13)

### Feat

- filter CareLink data to workout windows (#55)

## v0.24.0 (2026-03-12)

### Feat

- **TG-39**: optimize dashboard charts for mobile usability (#49)

### Fix

- **TG-33**: only show new data banner for newly inserted activities (#52)
- **TG-37**: address code review issues for overview page caching (#45)

## v0.23.0 (2026-03-11)

### Feat

- **TG-39**: optimize dashboard charts for mobile usability (#49)

### Fix

- **TG-37**: address code review issues for overview page caching (#45)

## v0.22.1 (2026-03-10)

### Fix

- allow missing CareLink SG readings
- **TG-37**: address code review issues for overview page caching (#45)

## v0.22.0 (2026-03-07)

### Feat

- **TG-28**: add Lightsail production deployment support (#42)

## v0.21.0 (2026-03-06)

### Feat

- visualise code structure with Mermaid class diagram (#41)

## v0.20.0 (2026-03-05)

### Feat

- **TG-34**: introduce mock data mode for safe full-stack local development (#40)

## v0.19.1 (2026-03-05)

### Fix

- auto-refresh questionnaire list after fetch (#39)

## v0.19.0 (2026-02-27)

### Feat

- **TG-32**: establish and implement consistent frontend color theme (#38)

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
