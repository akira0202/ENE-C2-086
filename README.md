# ENE-C2-086 — EnergyMethaneObservationContextBriefGenerator

> **Category**: Cat 2 (multi-step domain workflow)
> **Industry**: ENE

## Overview

This agent assembles a cited context brief from greenhouse-gas observation data that has
already been approved for use. You give it the observation extracts, a map of which assets the
observations relate to, notes on how the measurements were made, and the reporting template to
follow; it returns a brief in that template with every statement linked back to the source it came
from. It is aimed at environmental-review teams in energy and LNG operations who need the evidence
laid out before a qualified analyst looks at it.

It is read-only and restates only what it was given. It does not identify leaks, attribute emissions
to a particular asset, estimate figures beyond the supplied values, start field work, report a
regulatory breach, or control any equipment — the environmental owner keeps every judgement.

This is an agent template built with the **AGENTIC STAR** development platform and the
**AgentCore Framework**. It is intended to be taken as a starting point: fork it, adapt it to
your own data and policies, and run it inside your own AGENTIC STAR deployment.

## What it returns

Every run completes and says what happened.

| Result | When |
|---|---|
| The cited brief | the request meets the input contract and the brief passes the output check |
| A notice instead of a brief, with a code | the request is one you can correct (it is empty, is not the documented JSON, or breaks the input contract — the notice names what to send instead), or the assembled brief would have gone beyond what this agent reports, or would have carried personal data. No part of the brief is returned, and the notice never repeats what you sent |
| An error, with no output | the request is refused by the input screen, the brief carries an instruction addressed to the agent or credential-shaped content, or the run hits an internal inconsistency. These are never reported as a completed request |

The input contract, the codes and the full classification are in
[`docs/02_design.md`](docs/02_design.md).

## Requirements

**This template does not run standalone.** It requires:

| Requirement | Notes |
|---|---|
| **AGENTIC STAR platform** | The agent connects to the platform at start-up. Without it, start-up fails immediately (see *Behaviour without the platform* below). Deployment guides and API documentation: [AGENTIC STAR Developers](https://developers.fd.agenticstar.tm.softbank.jp/) |
| **AgentCore Framework** (`agenticstar-agentcore`) | Installed from PyPI as a dependency. |
| Python | >=3.11 |

```bash
pip install -e .
```

### Behaviour without the platform

The framework is designed to run **only** on AGENTIC STAR. There is no fallback or degraded
mode. If the platform is unreachable or the SDK version does not match, the agent raises
`PlatformRequired` during graph compile / start-up preflight rather than starting in a partially
working state. This is intentional — a half-running agent is worse than one that refuses to start.

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

Tests run without a platform connection. Running the agent itself does not.

## Project Structure

```
src/          agent implementation (nodes, services, schemas)
tests/        unit, integration and boundary tests
config/       agent configuration
docs/         design and test specifications
```

See `docs/` for the design specification and the test specification.

## Customising

1. Adjust `config/` for your own environment and policies.
2. Replace the knowledge sources and sample data with your own.
3. Review the node implementations under `src/nodes/` for domain-specific logic.
4. Re-run the test suite.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This template is published **as is**, by its individual author, under the MIT license. It carries
**no warranty and no support commitment**, and no organisation stands behind its behaviour or
fitness for any purpose. Issues and pull requests may or may not receive a response; that is at
the sole discretion of the repository owner.

