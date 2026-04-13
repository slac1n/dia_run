Run the test suite and analyze results.

Steps:
1. Run `uv run pytest --tb=short -q` to get a quick overview
2. If any tests fail:
   - Read the failing test files and the source files they test
   - Diagnose root causes
   - Suggest fixes with code snippets
3. If all tests pass, run `uv run pytest --cov=dia_run --cov-report=term-missing` and report:
   - Overall coverage percentage
   - Files with lowest coverage
   - Untested public methods worth covering
