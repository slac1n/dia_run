Update the architecture diagram at `docs/diagram.mmd` to reflect current code.

Steps:
1. Read the current `docs/diagram.mmd`
2. Scan all Python files under `src/dia_run/` for:
   - Classes, Pydantic models, Pandera DataFrameModels, Protocols, StrEnums
   - Their public methods, properties, and fields
   - Relationships: inheritance, composition, protocol implementation, dependencies
   - Function-only modules and their public functions
3. Compare what's in the diagram vs what's in the code
4. Report any discrepancies found
5. Update `docs/diagram.mmd` to match the current codebase
6. Validate the Mermaid syntax is correct
