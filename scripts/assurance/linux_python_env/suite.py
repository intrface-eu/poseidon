"""Run an explicit unittest module/class selection with zero-skip evidence.

Class selection records deliberate manifest exclusions; it never turns a skip
into success. Each invocation is wrapped in the guest runner's hard deadline.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import unittest


def flatten(suite):
    for value in suite:
        if isinstance(value, unittest.TestSuite):
            yield from flatten(value)
        else:
            yield value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--pattern", required=True)
    parser.add_argument("--class-name")
    parser.add_argument("--minimum", type=int, default=1)
    args = parser.parse_args(argv)
    if args.minimum < 1 or not Path(args.root).is_dir():
        parser.error("a real discovery root and positive minimum are required")
    suite = unittest.TestLoader().discover(args.root, pattern=args.pattern)
    discovered = list(flatten(suite))
    if args.class_name:
        selected = [test for test in discovered if type(test).__name__ == args.class_name]
        if not selected:
            print("Explicit class selector matched no tests", file=sys.stderr)
            return 1
    else:
        selected = discovered
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected))
    record = {"schema_version": "poseidon.linux-python-suite.v1", "root": args.root,
              "pattern": args.pattern, "class_name": args.class_name,
              "discovered_ids": [test.id() for test in discovered],
              "selected_ids": [test.id() for test in selected],
              "deselected_ids": [test.id() for test in discovered if test not in selected],
              "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "skipped": len(result.skipped), "expected_failures": len(result.expectedFailures),
              "unexpected_successes": len(result.unexpectedSuccesses), "required_minimum": args.minimum,
              "physical_operations_authorized": False}
    accepted = result.wasSuccessful() and result.testsRun >= args.minimum and not any(record[key] for key in ("skipped", "expected_failures", "unexpected_successes"))
    record["accepted"] = accepted
    print("POSEIDON_SUITE_RESULT=" + json.dumps(record, sort_keys=True))
    return 0 if accepted else 1


if __name__ == "__main__":
    sys.exit(main())
