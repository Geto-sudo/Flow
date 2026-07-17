# specs/contract-tests/

# Flow Conformance Test Suite

| Field | Value |
|---|---|
| **Spec version** | 1.0.0 |
| **Status** | Draft |

This directory contains the **executable conformance tests** for every spec in `specs/`. A Flow-compliant implementation must pass these tests.

## Why conformance tests are part of the spec

A spec without tests is documentation. A spec with tests is a contract.

Conformance tests are:

- **Executable.** You can run them. They produce pass/fail.
- **Implementation-agnostic.** They test behavior, not implementation.
- **Shared.** Every implementation runs the same tests. Two implementations are "compatible" if both pass the same tests.
- **Versioned with the spec.** When a spec changes, the corresponding tests change.

## Structure

```
contract-tests/
├── README.md                       ← you are here
├── actions/                        ← tests for spec/actions/*.json
│   ├── trim.test.py
│   ├── split.test.py
│   ├── export.test.py
│   └── ...
├── timeline/                       ← tests for spec/timeline/*
├── project/                        ← tests for spec/project/flow.json
├── plugins/                        ← tests for spec/plugins/*
├── abi/                            ← tests for spec/abi/*
│   ├── ref-plugin.c
│   ├── test-driver.c
│   └── Makefile
├── errors/                         ← tests for spec/errors/*
├── events/                         ← tests for spec/events/*
├── protocols/                      ← tests for spec/protocols/*
│   ├── mcp-surface.test.py
│   └── http-api.test.py
├── validation/                     ← tests for spec/validation/*
└── runner/                         ← the test runner scripts
    ├── run.sh
    └── run.py
```

## Running the tests

Each subdirectory has a `run.sh` (POSIX) and/or `run.py` (Python) that runs all tests in that subdirectory. The top-level `run.sh` runs all subdirectories.

```bash
$ ./contract-tests/run.sh

Running contract-tests/actions ...
  trim.test.py .................. PASS
  split.test.py ................. PASS
  export.test.py ................ PASS
  ...

Running contract-tests/timeline ...
  otio-roundtrip.test.py ........ PASS
  metadata.test.py .............. PASS
  ...

Running contract-tests/plugins ...
  ref-plugin.c .................. PASS
  manifest-validation.test.py ... PASS
  ...

Running contract-tests/errors ...
  flow_001.test.py .............. PASS
  flow_002.test.py .............. PASS
  ...

Total: 42 tests, 42 passed, 0 failed.
```

## What a passing run means

If a runtime passes all tests in `contract-tests/`, it is **Flow v1.0 compliant**. It can:

- Read and write Flow projects in the canonical format.
- Validate, plan, and execute every action in the catalog.
- Emit the right events for the right actions.
- Return the right error codes for the right failures.
- Load and call v1 plugins.
- Speak the v1 MCP surface to any MCP client.

## What a failing run means

A failure indicates a **specification drift**: either the spec is wrong, or the implementation is wrong. The fix is:

1. If the spec is correct: fix the implementation.
2. If the spec is wrong: amend the spec (via a new ADR) and update the tests.
3. The test itself is never wrong (it expresses the spec).

## Adding a new conformance test

To add a test for a new spec file or a new spec version:

1. Add the test file in the appropriate subdirectory.
2. The test should:
   - Load the spec.
   - Construct a valid example input.
   - Assert the runtime accepts it.
   - Construct an invalid input.
   - Assert the runtime rejects it with the right error code.
3. Add the test to the `run.sh` script.
4. Update the count in the README.

## Versioning

Conformance tests are versioned with the spec they test. The test suite is tagged with the spec version it validates. An implementation that targets spec v1.0.0 must pass the conformance tests for v1.0.0; the same implementation may or may not pass tests for v1.1.0.
