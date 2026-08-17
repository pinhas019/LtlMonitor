# Archive: pre-adapter standalone clone

Rescued 2026-08-17 from `/home/humanoid/LtlMonitor`, a second clone of this repo
that was abandoned at merge-base `11328d2` (2026-06-04) and has since been
deleted. It predates the sensor-adapter architecture entirely — it still had
`llm_client.py` and no `generic_client.py` / `sensor_adapter.py` / `formulas_g1.json`.

**Everything here is stale. Nothing here is the current design.** It is kept only
because these four files existed in no other git object on the machine.

- `system_description.tex` / `.pdf` — LaTeX overview of the *old* LLM-fallback
  hybrid evaluator. The current equivalent is `system_description.md` in the repo
  root. From the clone's unpushed commit `19b8477`.
- `formulas.regenerated.json`, `skill_description.regenerated.md` — uncommitted
  `generate_formulas.py` output from 2026-06-16, against the pre-adapter
  `SENSOR_SCHEMA`. They will not pass `test_adapter_sensor_eval_contract.py`.

The clone's full history (all 10 commits, including `19b8477`) is preserved as a
ref in this repo:

    git log refs/archive/pre-adapter-standalone
