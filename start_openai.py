"""Start JARVIS with OpenAI without storing an API key on disk."""
import copy
import os
import json
import platform


def configure():
    from memory import config_manager as cm

    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise SystemExit("Defina OPENAI_API_KEY no ambiente antes de iniciar o Jarvis.")
    # Preserve every saved setting. Keys are injected into runtime copies only.
    data = copy.deepcopy(cm.load_api_keys())
    providers = data.setdefault("providers", {})
    providers.update(mode="pipeline", sidecar="openai_compat", sidecar_first=True)
    providers["pipeline"] = {"stt": "whisper", "llm": "openai_compat", "tts": "system_tts"}
    creds = providers.setdefault("creds", {})
    creds.setdefault("openai_compat", {}).update(
        base_url="https://api.openai.com/v1",
        model=os.environ.get("JARVIS_OPENAI_MODEL", "gpt-4.1"), vision=True)
    creds.setdefault("whisper", {}).update(
        backend="api", base_url="https://api.openai.com/v1", model="whisper-1")
    creds.setdefault("system_tts", {})
    data.setdefault("os_system", platform.system())
    # No Gemini fallback, including when an old key remains in the settings.
    os.environ["JARVIS_OPENAI_ONLY"] = "1"
    cm.ensure_config_dir()
    cm.CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    original = cm.load_api_keys

    def runtime_config():
        current = original()
        block = current.setdefault("providers", {}).setdefault("creds", {})
        for pid in ("openai_compat", "whisper"):
            block.setdefault(pid, {})["api_key"] = key
        return current

    cm.load_api_keys = runtime_config


if __name__ == "__main__":
    configure()
    from main import main
    main()
