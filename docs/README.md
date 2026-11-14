# Artaud documentation

[Project overview](../README.md) · [Live dashboard](https://frontend-nine-iota-19.vercel.app/)

The live frontend requires the owner's access key and a running PC backend. A local checkout works independently of Vercel and ngrok.

## Choose a guide

| Goal                                                       | Read                                                                                           |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Run the project for the first time                         | [README quick start](../README.md#quick-start)                                                 |
| Understand chunk placement, integrity and failure recovery | [Architecture](ARCHITECTURE.md)                                                                |
| Present the project or connect Vercel to the PC            | [Demo and HTTPS setup](DEMO.md)                                                                |
| Fix access, JOINING, upload or persistence problems        | [Troubleshooting](TROUBLESHOOTING.md)                                                          |
| Call the REST API                                          | [HTTP contract](../contracts/api-contract.md) and [local API docs](http://127.0.0.1:8000/docs) |
| Develop or review the controller                           | [Controller guide](CONTROLLER.md)                                                              |
| Develop or review the web interface                        | [Frontend guide](FRONTEND.md) and [design system](../DESIGN.md)                                |
| Understand live graphs, replay and telemetry limits        | [Live system explorer](LIVE_SYSTEM.md)                                                         |
| Reproduce the automated and real-container checks          | [Acceptance and testing](ACCEPTANCE.md)                                                        |
| Integrate recovery with database operations                | [Database helpers](../contracts/db-helpers.md) and [schema](../contracts/db-schema.md)         |
| Continue in another editor, Codex or Claude                | [Current handoff](HANDOFF.md), then [AGENTS.md](../AGENTS.md)                                  |

## Source of truth

The current application and shared contracts define behavior. The acceptance guide records dated execution evidence; the handoff records publication, local environment details and continuation decisions. Screenshots show a captured observation, not a guarantee of current availability.

Older plans, research and reviews under `superpowers/`, `research/` and `reviews/` preserve design history. Their proposed or pending items may have been completed or superseded. In particular, `tests/live_controller_check.py` is historical pre-recovery verification; use `tests/test_end_to_end.py` for the current integrated system.

All integrated work is on the repository's default branch, `master`. Member A owns the controller/frontend; Member B owns workers/recovery; contracts and end-to-end acceptance are shared.
