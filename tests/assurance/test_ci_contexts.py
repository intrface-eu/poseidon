"""Regression for runner context in the repository's block-style CI env layout.

This checks one known context rule; it is not a GitHub Actions schema validator.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


def outer_env_runner_references(text: str) -> list[int]:
    lines = text.splitlines()
    failures = []
    for index, line in enumerate(lines):
        if not re.match(r"^(?:env|    env):", line):
            continue
        indentation = len(line) - len(line.lstrip())
        block = [line]
        for following in lines[index + 1:]:
            if not following.strip() or following.lstrip().startswith("#"):
                continue
            if len(following) - len(following.lstrip()) <= indentation:
                break
            block.append(following)
        if re.search(r"\$\{\{\s*runner\s*(?:\.|\[)", "\n".join(block)):
            failures.append(index + 1)
    return failures


class CIContextTests(unittest.TestCase):
    def test_rejects_direct_runner_context_in_global_and_job_env(self) -> None:
        for text in (
            "env:\n  CACHE: ${{ runner.temp }}/cache\njobs:\n  check:\n    runs-on: ubuntu-24.04\n",
            "jobs:\n  check:\n    env:\n      CACHE: ${{ runner.temp }}/cache\n    steps: []\n",
        ):
            with self.subTest(text=text):
                self.assertTrue(outer_env_runner_references(text))

    def test_allows_runner_context_in_step_env(self) -> None:
        text = "jobs:\n  check:\n    env:\n      FIXED: local\n    steps:\n      - name: browser\n        env:\n          CACHE: ${{ runner.temp }}/cache\n        run: command\n"
        self.assertEqual(outer_env_runner_references(text), [])

    def test_repository_does_not_regress_to_outer_runner_env(self) -> None:
        # https://docs.github.com/en/actions/reference/workflows-and-actions/contexts
        workflow = ROOT / ".github/workflows/check.yml"
        self.assertEqual(outer_env_runner_references(workflow.read_text()), [], str(workflow))


if __name__ == "__main__":
    unittest.main()
