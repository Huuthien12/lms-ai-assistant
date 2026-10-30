"""One-time patch for DeepTutor-verified benchmark providers.
Run from the D:\\DeepTuTor-verified project root with its Python interpreter.
"""
from pathlib import Path
import ast
import shutil
import sys

ROOT = Path.cwd()
BASE = ROOT / 'backend' / 'services' / 'ai'
FILES = ['model_config.py', 'benchmark_cli.py', 'deeptutor_llm_worker.py']
for name in FILES:
    if not (BASE / name).is_file():
        sys.exit(f'Missing {BASE / name}; run from project root')

patches = {}

def replace_once(s, old, new, name):
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f'{name}: expected one match, found {count}: {old[:100]!r}')
    return s.replace(old, new, 1)

p = BASE / 'model_config.py'
s = p.read_text(encoding='utf-8')
s = replace_once(s, '{"ollama", "openai", "gemini", "anthropic"}', '{"ollama", "openai", "gemini", "anthropic", "groq", "openrouter"}', p.name)
patches[p] = s

p = BASE / 'benchmark_cli.py'
s = p.read_text(encoding='utf-8')
s = replace_once(s, 'Cloud target (openai, gemini, anthropic); requires explicit opt-in', 'Cloud target (openai, gemini, anthropic, groq, openrouter); requires explicit opt-in', p.name)
s = replace_once(s, 'provider not in {"openai", "gemini", "anthropic"}', 'provider not in {"openai", "gemini", "anthropic", "groq", "openrouter"}', p.name)
s = replace_once(s, '"anthropic": "ANTHROPIC_API_KEY"}', '"anthropic": "ANTHROPIC_API_KEY", "groq": "GROQ_API_KEY",\n                 "openrouter": "OPENROUTER_API_KEY"}', p.name)
s = replace_once(s, '    targets = []\n    for provider, model in specs:', '''    base_urls = {"groq": "https://api.groq.com/openai/v1",
                 "openrouter": "https://openrouter.ai/api/v1"}
    targets = []
    for provider, model in specs:''', p.name)
s = replace_once(s, 'timeout_seconds=args.timeout, api_key_env=key_names.get(provider),\n', 'timeout_seconds=args.timeout, api_key_env=key_names.get(provider),\n            base_url=base_urls.get(provider),\n', p.name)
patches[p] = s

p = BASE / 'deeptutor_llm_worker.py'
s = p.read_text(encoding='utf-8')
s = replace_once(s, 'import sys\n', 'import sys\nimport urllib.error\nimport urllib.request\n', p.name)
needle = 'async def execute(request):\n'
helper = '''def _openai_compatible(request):
    """Groq/OpenRouter chat completions, without changing DeepTutor's provider registry."""
    endpoints = {
        "groq": "https://api.groq.com/openai/v1",
        "openrouter": "https://openrouter.ai/api/v1",
    }
    name = request["provider"]
    key_env = {"groq": "GROQ_API_KEY", "openrouter": "OPENROUTER_API_KEY"}[name]
    if request.get("api_key_env") != key_env:
        return {"status": "error", "error_code": "INVALID_API_KEY_CONFIG"}
    key = os.getenv(key_env, "").strip()
    if not key:
        return {"status": "error", "error_code": "PROVIDER_UNCONFIGURED"}
    # Use fixed trusted endpoints; never accept a user-controlled destination for a secret.
    endpoint = endpoints[name] + "/chat/completions"
    messages = []
    if request.get("system_prompt"):
        messages.append({"role": "system", "content": request["system_prompt"]})
    messages.append({"role": "user", "content": request["prompt"]})
    payload = {
        "model": request["model"],
        "messages": messages,
        "temperature": float(request["temperature"]),
        "max_tokens": int(request["max_tokens"]),
        "stream": False,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint, data=data, method="POST",
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=100) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        status = error.code
        return {"status": "error", "error_code": (
            "RATE_LIMITED" if status == 429 else
            "PROVIDER_AUTH_ERROR" if status in (401, 403) else
            "MODEL_UNAVAILABLE" if status == 404 else
            "PROVIDER_HTTP_ERROR"
        )}
    except (urllib.error.URLError, TimeoutError):
        return {"status": "error", "error_code": "TIMEOUT_OR_NETWORK_ERROR"}
    try:
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            return {"status": "error", "error_code": "EMPTY_RESPONSE"}
        usage = body.get("usage")
        return {"status": "success", "content": content,
                "usage": usage if isinstance(usage, dict) else {}}
    except (KeyError, IndexError, TypeError):
        return {"status": "error", "error_code": "INVALID_RESPONSE"}


'''
s = replace_once(s, needle, helper + needle, p.name)
s = replace_once(s, 'async def execute(request):\n', '''async def execute(request):
    if request.get("provider") in {"groq", "openrouter"}:
        return await asyncio.to_thread(_openai_compatible, request)
''', p.name)
patches[p] = s

for path, content in patches.items():
    ast.parse(content, filename=str(path))
for path, content in patches.items():
    backup = path.with_suffix(path.suffix + '.before_groq_openrouter.bak')
    if backup.exists():
        sys.exit(f'Backup already exists: {backup}; patch not applied')
for path, content in patches.items():
    backup = path.with_suffix(path.suffix + '.before_groq_openrouter.bak')
    shutil.copy2(path, backup)
    path.write_text(content, encoding='utf-8', newline='\n')
    print(f'Patched: {path.relative_to(ROOT)} (backup: {backup.name})')
print('Done. Existing KB and benchmark outputs were not touched.')
