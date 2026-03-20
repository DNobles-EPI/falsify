# falsify

`falsify` is a minimal FSM orchestrator that drives an AI coding agent through a continuous improvement loop:
  
plan → do → test → fix → commit → PR → CI → repeat.

It's an AI coding agent for test driven development.  
  
The test state is foundational.  
  
The goal of the tests is to break things, figure out what happened, and fix it. 
  
Continuously building structured execution and validation.  

_In computer science, there is a structured proposal for an "Antifragile Software Manifesto", to react to traditional system designs. The major idea is to develop antifragility by design, building a system which improves from environmental inputs._ [ref: Antifragile](https://en.wikipedia.org/wiki/Antifragile_(book))
  
[Antifragile Manifesto](https://www.danielrusso.org/files/2016Antifragile_Manifesto.pdf)
   
## State Machine

![State Machine](docs/statemachine.png)

| State | Description |
|---|---|
| `PLAN` | Load pending todos (review comments, CI failures, backlog) |
| `DO` | Execute todos; the agent modifies the working tree |
| `LOCAL_VERIFY` | Check git status; route to tests if dirty, PR sync if clean |
| `RUN_IMPACTED_TESTS` | Run pytest on tests affected by changed files |
| `FIX_FAILING_TEST` | Agent fixes one failing test at a time |
| `COMMIT` | Commit clean working tree to feature branch |
| `PR_SYNC` | Push branch and create/update PR against `dev` |
| `WAIT_CI` | Poll GitHub checks and review status |
| `TRIAGE_CI_FAIL` | Convert CI failure logs into actionable todos |
| `DONE` | PR approved; cycle complete |

## Usage

```python
from falsify import AgentFSM, Context

fsm = AgentFSM()
fsm.run()
```

CLI:

```bash
falsify run --agent-backend codex
falsify run --agent-backend codex-oss
falsify doctor --agent-backend codex
falsify doctor --agent-backend codex-oss
```

## Local OSS Backend

`codex-oss` uses Codex CLI with Ollama as the local provider and targets `gpt-oss:20b`.

In WSL, two topologies are supported:
- Ollama running inside the Linux distro
- Ollama running on the Windows host and reached from WSL

Setup:

```bash
# Standard Codex backend
./scripts/setup.sh codex

# Local OSS backend with autodetection
./scripts/setup.sh codex-oss auto

# Force a specific Ollama topology
./scripts/setup.sh codex-oss wsl
./scripts/setup.sh codex-oss windows
```

The setup script validates the exact toolchain that `falsify` uses. For `codex-oss`, it checks Codex, reaches Ollama, ensures `gpt-oss:20b` is present, and performs a non-interactive Codex OSS self-check.

## Development

```bash
# Run tests
make test

# Generate state machine diagram
make docs
```

## TODOs
- test suite
- doctor helper
- all cli integration and docs
- prompts for LLMs
