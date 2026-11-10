# exercise evidence input and output paths during development.
import json
from pathlib import Path

original = json.loads(
    Path("evidence_report_v2.json").read_text(encoding="utf-8")
)

test = json.loads(
    Path("evidence_report_test.json").read_text(encoding="utf-8")
)

assert original == test

print("Evidence report reproducibility test passed!")