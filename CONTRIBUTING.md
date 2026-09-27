# Contributing to Poseidon Trident

We welcome work on passive acoustic monitoring, marine biology and bioacoustics, embedded and acoustic engineering, reproducible validation, and documentation. Pilot farms, research partners and funding collaborators can find the project at https://poseidon.intrface.eu or contact basic@intrface.eu. Maintainer: Alex Basic, director of INTRFACE j.d.o.o.

Open an issue at https://github.com/intrface-eu/poseidon-trident/issues before a large change, especially one involving hardware, emissions, data collection or scientific claims. Do not upload recordings, private data, credentials, or vendor CAD/datasheets to issues or pull requests. Send security reports privately as described in [SECURITY.md](SECURITY.md).

## Setup and checks

Install Python 3.11+, [uv](https://docs.astral.sh/uv/), [Bun](https://bun.sh/) and Make. From the repository root:

```sh
make setup
make check
make test
```

For source-only Python checks, run `make check-python` and `make test-python`. Research and assurance suites run with `make test-research` and `make test-assurance`; run `make prepare-verification` first when isolated environments are needed. See [README.md](README.md) for the local monitor and the scope of what these checks establish. Hardware tests and compile-only targets do not authorize device operation.

Use the Developer Certificate of Origin sign-off on each commit (`git commit -s`); the sign-off states that you have the right to submit the contribution under the project's licenses. See [NOTICE](NOTICE) for the path-specific license split. Keep changes scoped, describe the observed behavior and checks in your pull request, and retain attribution for third-party material.

Much of this code and documentation was written with AI coding assistants under the maintainer's review. Contributions are reviewed to the same standards regardless of who or what wrote them; contributors remain responsible for their submissions.
