# Managed-project Cortex root bridge template

Future normalized projects should keep a root `PROJECT_CONTROL_CENTER.cmd` that opens Cortex for that project. The project carries `project.control.json` and any domain adapter/plugin; Cortex owns universal project operations.

The template resolves Cortex from `CORTEX_HOME`, a sibling `Cortex` checkout, or `%LOCALAPPDATA%\Cortex\bin`. Customize only the locator policy, not project-operation logic.
