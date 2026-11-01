#!/bin/sh
set -eu
mkdir -p /logs/verifier
/usr/bin/python3 /tests/verify.py --input /tests/original_input.xlsx --goal /tests/reference.xlsx --output /app/output.xlsx --profile /tests/runtime_profile.json --reward /logs/verifier/reward.txt --report /logs/verifier/diagnostics.json
