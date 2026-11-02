# Federated audit harness

Real hospitals often can't move patient data. Federated platforms run code inside each site and return only summaries. This harness imitates that on a laptop.

## The rule

**Only summary statistics leave a hospital.** Counts, histograms, means and covariances, sketches and ANOVA pieces are fine. Rows, case IDs and patient IDs are not. That includes anything your code sends to an external LLM or API: if rows reach a model provider, they have left the hospital.

## Using it

Write a function that takes one hospital folder and returns a dict:

```python
from pathlib import Path

def audit(node: Path) -> dict:
    ...
    return {"n_cases": 412, "aaa_counts": {"True": 57, "False": 355}}
```

Run it across every hospital:

```bash
python harness/harness.py --data path/to/release --audit my_audit:audit --out summaries.json
```

Then combine `summaries.json` centrally however you like. That's where the interesting work is.

`example_audit.py` is a deliberately simple audit that passes. It catches some planted problems and misses others.

## What gets rejected

- pandas objects
- any list whose length equals the hospital's case count
- any case or patient identifier, as a value or as a key
- more than a million numbers in total

Integer counts below 5 produce a warning, not a rejection. In real data, small cells can identify people.

This is a teaching harness, not a privacy guarantee. You can sneak rows past it if you try. Don't. Design an audit that works within the rule, because on a real platform that's the only kind that runs.

## Requirements

Python 3.10+, `numpy`, `pandas`, `pyarrow`.
