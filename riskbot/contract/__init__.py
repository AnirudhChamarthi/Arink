"""Riskbot v2 contract: the only module every component may import.

Contents
--------
types        data transfer objects (inputs, outputs, traces, runs)
catalog      the model catalogue, questions and default plans  <- links core, services, adapters and UI
ports        Protocol interfaces between components
rules        shared business rules (ratings, verdicts)
conformance  parameter resolution and output validation against the catalogue
hashing      canonical ids, hashes and seeds
tracing      TraceBuilder used by every model
errors       boundary exceptions
fakes        deterministic test doubles of every port (tests only)

See CONTRACT.md for the full specification, ownership and change process.
"""

CONTRACT_VERSION = "2.0.0"
