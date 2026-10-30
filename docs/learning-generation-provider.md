# Quiz/Flashcard generation provider

This setting affects only verified Quiz and Flashcard generation. AI Tutor chat,
retrieval, benchmark targets, Moodle authorization, and publications keep their
existing configuration.

Local default:

```dotenv
LEARNING_GENERATION_PROVIDER=ollama
LEARNING_GENERATION_MODEL=qwen2.5:3b
LEARNING_GENERATION_PROVIDER_TIMEOUT_SECONDS=120
```

Explicit Groq opt-in:

```dotenv
LEARNING_GENERATION_PROVIDER=groq
LEARNING_GENERATION_MODEL=qwen/qwen3.8-27b
LEARNING_GENERATION_PROVIDER_TIMEOUT_SECONDS=120
GROQ_API_KEY=<environment-secret>
```

Selecting `groq` permits verified Moodle excerpts used by Quiz/Flashcard prompts
to be sent to Groq. The key is read from the process environment and is never
placed in provider payloads, logs, benchmark records, or application responses.
There is no automatic fallback between Groq and Ollama.
