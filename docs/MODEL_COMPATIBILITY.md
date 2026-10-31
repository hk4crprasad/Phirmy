# Model compatibility research

Checked 22 October 2026 against primary documentation. Recheck before adding a model preset; model names alone do not establish parameter support.

| API                            | Output cap used by this platform                                   | Temperature                            |
| ------------------------------ | ------------------------------------------------------------------ | -------------------------------------- |
| OpenAI Responses               | `max_output_tokens`                                                | Omitted by default                     |
| Modern OpenAI Chat Completions | `max_completion_tokens`                                            | Omitted by default                     |
| Compatible/legacy Chat         | Profile-selected `max_tokens`, `max_completion_tokens`, or omitted | Only explicit documented profile value |

OpenAI deprecates Chat's `max_tokens` and documents limitations for reasoning models; `max_completion_tokens` includes reasoning and visible output. [Chat parameter reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).

Sampling support can depend on reasoning effort. The current latest-model guide describes conditional support rather than a universal ban on temperature for every newer model. A reasoning budget also affects whether a small cap leaves room for visible output. [Latest model guide](https://developers.openai.com/api/docs/guides/latest-model), [requested default model](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

## Implemented policy

Environment: `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENAI_API_STYLE=auto|responses|chat_completions`, `OPENAI_TOKEN_PARAMETER=auto|max_tokens|max_completion_tokens|max_output_tokens|none`, `OPENAI_REASONING_EFFORT=auto|…`. Auto chooses Responses for api.openai.com; custom hosts default to Chat. No environment temperature is sent. New provider-specific defaults must be researched, not inferred from a model name.

Workspace profiles require a public documentation URL, explicit API/cap choices, optional documented temperature/reasoning effort, and a completed streaming test with an inert tool schema. The server stores source URL/date/content hash and probe latency. Checking that a parameter name appears in a page is a guard, **not semantic proof** of model-specific support; the operator must review restrictions. The probe verifies visible streaming and schema acceptance, not real tool reasoning or every context size.

Only input-validation failures before a stream begins can negotiate token/temperature parameters. Never replay a turn after text or a tool result has been emitted. Timeout/stream failure requires reconciliation at the application level.

Fish's custom-LLM contract uses OpenAI Chat SSE and tool calls; it delegates parameter defaults to the endpoint. This project implements its own control/media runtime with direct Fish TTS, not the Fish hosted Agents runtime. [Fish custom LLM](https://docs.fish.audio/agents/build/custom-llm), [Fish tools reference](https://docs.fish.audio/agents/build/webhook-tools).

## Supplied Azure deployment

The current env requests gpt-6-luna at the supplied Azure /openai/v1 endpoint. Explicit Responses/max_output_tokens and reasoning none, with no temperature, follow [Microsoft v1 documentation](https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle) and [reasoning guidance](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/reasoning). The initial DeploymentNotFound was resolved after the user deployed this exact target. Actual Responses streaming and function-call/result round trip now pass. The model catalog is not a list of active deployments, and no alternate target was substituted.

## Compatible GPT cache-usage accounting

GPT-5.6/6-compatible gateway usage is parsed independently of whether the gateway
accepts OpenAI-specific request extensions. When the provider reports aggregate
cache writes without a lifetime split and this adapter requested no override, the
parser uses the documented 30-minute default. Explicit lifetime counts must still
sum correctly. Cache input is reserved before the request and billed once in its
matching bucket; malformed or unrecognized usage retains its review hold. Host
checks continue to protect optional request parameters. See the [official cache
lifetime and usage contract](https://developers.openai.com/api/docs/guides/prompt-caching#cache-lifetime).
