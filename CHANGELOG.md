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
