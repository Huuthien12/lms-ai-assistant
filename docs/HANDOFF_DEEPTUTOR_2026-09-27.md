# DeepTutor handoff — 2026-09-27

## Current state

- Parent repository branch: `thien/deeptutor`.
- DeepTutor source commit: `1d9f6273eb468268574163fe3539daa9dd87af5d`.
- Working components: Ollama with `qwen2.5:3b`, `nomic-embed-text`, `int1339-python` retrieval, Vietnamese and English KB grounding, original-query language propagation, Windows UTF-8 CLI output, and terminal-turn lifecycle waiting.
- `data/user/settings/model_catalog.json` is local runtime configuration and must not be committed.

## Remaining blocker

The installed official `qwen3:4b` Ollama artifact/template forces an opening `<think>` generation prefix. Native `think:false` fails independently of DeepTutor: reasoning is returned in ordinary `content`, followed by a stray `</think>`. Refreshing the official model returned the same artifact. The failed local alias `qwen3:4b-deeptutor` was removed and must not be used. DeepTutor avoids this runtime issue by using `qwen2.5:3b`.

Observed performance in affected runs:

- Direct native `think:false` still produced hundreds of reasoning tokens.
- `qwen3:4b` Vietnamese RAG took approximately 150-162 seconds and English RAG exceeded approximately 180 seconds.
- With `qwen2.5:3b`, Vietnamese RAG passed in 66.45 seconds and English RAG passed in 25.96 seconds; both cited `3 - Ham.pdf` and had no reasoning leakage.

Do not switch DeepTutor back to `qwen3:4b` unless its Ollama model-template compatibility is resolved.

## Preserved source changes

- `deeptutor/agents/chat/agentic_pipeline.py`: preserve normalized language codes instead of collapsing every non-Chinese language to English.
- `deeptutor/agents/chat/capability.py`: choose response language from the original user query before constructing the chat pipeline.
- `deeptutor/agents/chat/prompt_blocks.py`: preserve the normalized language through prompt assembly.
- `deeptutor/services/prompt/language.py`: support Vietnamese directives and detect Vietnamese, English, and Chinese query text while retaining fallback behavior.
- `deeptutor_cli/common.py`: configure safe UTF-8 Windows output and wait for the terminal turn state after streaming; explicit interruption/cancellation remains intact.
- `docs/HANDOFF_DEEPTUTOR_2026-09-27.md`: this resume record in the parent repository.

## Removed failed experiments

- Reverted the native Ollama `/api/chat` workaround from `deeptutor/agents/chat/agent_loop.py`.
- Removed `qwen3-4b-deeptutor.Modelfile`.
- Removed the local Ollama alias `qwen3:4b-deeptutor`.
- Official `qwen3:4b`, `nomic-embed-text`, the KB, retrieval, and embeddings were not changed.

## Next session order

1. Test `/deeptutor/query` with the existing `int1339-python` KB.
2. Review and commit the parent repository submodule-pointer update and this handoff.
3. Continue LMS integration.
