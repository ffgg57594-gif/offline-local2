#!/usr/bin/env python3
import json, os
out = os.path.join("app", "src", "main", "assets", "config_calibrated.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w") as f:
    json.dump({"STRICT_SIMILARITY_THRESHOLD": 0.62, "VERIFICATION_THRESHOLD": 0.55}, f)
print("wrote", out)
