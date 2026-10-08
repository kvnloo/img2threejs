# Dreamloop-RSI mesh-fidelity experiments

Downstream-only research harness for `docs/RFC_DREAMLOOP_RSI_MESH_FIDELITY.md`.

The first slice tests one claim: recorded mesh-search histories can improve the order in which a fixed render budget is spent without changing the builder or evaluator.

Run:

```bash
PYTHONPATH=experiments/dream_rsi_mesh_fidelity \
python3 -m unittest discover -s experiments/dream_rsi_mesh_fidelity/tests -v
```

Current prototype:

- pure stdlib;
- exact replay over recorded nodes only;
- out-of-support counterfactuals fail loud;
- hard-gated high-IoU candidates cannot win;
- fixed evaluation budget;
- coordinate-order policy;
- history-derived coordinate priority;
- ties keep the incumbent.

Next: adapt real `fit_against_divine_eye()` evaluations into the world schema, then collect complete first-step neighborhoods for public/demo references.
