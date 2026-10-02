# Contract for the inference-layer session

The user is developing the inference layer in the separate nucybersec/mailkit
session. This pipeline adds no changes to that stack. Its deployment contract is:

| Concern | Contract |
| --- | --- |
| Local student | `google/gemma-4-E4B-it`, pinned revision in `config.toml` |
| Cloud student | `Qwen/Qwen3.8-27B`, pinned revision in `config.toml` |
| Local serving | Ollama native API plus `/v1/chat/completions` |
| Candidate tag | `trajectory-gemma-admin:candidate-JOB_ID_PREFIX` |
| Production alias | `trajectory-gemma-admin:active` |
| Rollback tag | `trajectory-gemma-admin:previous-JOB_ID_PREFIX` |
| Memory | Existing session-recall and neo4j-sessions, or the read-only `recall` function |
| Feedback | `TrajectoryInterceptor` captures the deployed model's new sessions |
| Cloud transport | GPU host/submission transport still to be chosen |

The Ollama adapter streams a GGUF into the blob API, creates the unique candidate
tag, records its engine digest, and binds evaluation to that tag. The model's native
tool parser must work in the installed Ollama version: function-calling regression
cases will reject an incompatible renderer/parser. Before promotion it checks the
candidate digest again. Promotion copies only the dedicated active alias, preserves
a backup alias, checks generation, and restores the previous tag if health fails.

Set `LLAMA_CPP_DIR` to a tested llama.cpp checkout with `convert_hf_to_gguf.py` and
`build/bin/llama-quantize`. The exporter merges the adapter on CPU, converts to FP16
GGUF, and quantizes to Q4_K_M. It needs RAM/disk for the unquantized model; conversion
support for the exact architecture must be tested on the chosen training host.

Set the baseline tag to the one the inference layer actually serves. The example
uses `gemma4:e4b`; it does not pull or create that baseline. Enable training only
after a real GPU worker and a sufficient regression suite are configured. Enable
automatic promotion only when the inference layer is ready to consume the managed
active alias. No service was restarted and no model was installed during development.

LM Studio can be useful as a manual GGUF comparison and debugging interface. It is
optional for this pipeline: its OpenAI-compatible tool-calling endpoint can be used
as a baseline/candidate endpoint without changing the corpus or training code.
Keep Ollama as the initial automated serving owner to avoid two independent model
lifecycle controllers. If LM Studio becomes the serving owner, replace the import,
reload, health, and rollback commands as one coherent adapter.

References: [Ollama create API](https://docs.ollama.com/api/create),
[Ollama import](https://github.com/ollama/ollama/blob/main/docs/import.mdx),
[LM Studio tool use](https://lmstudio.ai/docs/developer/openai-compat/tools).
