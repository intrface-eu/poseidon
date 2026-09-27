"""Run one unittest discovery root; incomplete checks never pass assurance.

These are digital checks only, not physical qualification or release approval.
"""
from __future__ import annotations

import argparse
import sys
import unittest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-s", "--start-directory", required=True)
    parser.add_argument("-p", "--pattern", default="test*.py")
    parser.add_argument("-t", "--top-level-directory")
    parser.add_argument("--min-tests", type=int, default=1)
    args = parser.parse_args(argv)
    if args.min_tests < 1:
        parser.error("--min-tests must be greater than zero")
    suite = unittest.TestLoader().discover(
        start_dir=args.start_directory,
        pattern=args.pattern,
        top_level_dir=args.top_level_directory,
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    incomplete = (
        result.testsRun < args.min_tests
        or bool(result.skipped)
        or bool(result.expectedFailures)
        or bool(result.unexpectedSuccesses)
    )
    accepted = result.wasSuccessful() and not incomplete
    status = "PASS" if accepted else "INCOMPLETE" if incomplete else "FAILED"
    print(
        f"Assurance {status}: tests_run={result.testsRun}, "
        f"failures={len(result.failures)}, errors={len(result.errors)}, "
        f"skipped={len(result.skipped)}, expected_failures={len(result.expectedFailures)}, "
        f"unexpected_successes={len(result.unexpectedSuccesses)}, required_minimum={args.min_tests}. "
        "Digital checks only; no physical qualification or release approval.",
        file=sys.stderr,
    )
    return 0 if accepted else 1


if __name__ == "__main__":
    sys.exit(main())
