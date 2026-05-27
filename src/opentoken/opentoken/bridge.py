import copy
import json
from datetime import UTC, datetime
from pathlib import Path

from opentoken.models.discovery import load_model_catalog
from opentoken.storage._atomic import write_json_atomic


def build_algae_provider_patch(base_url: str, api_key: str) -> dict[str, object]:
    # Pull the live discovered model list (per logged-in provider) instead of a
    # hardcoded one. The previous behaviour wrote a stale list of ~30 baked-in
    # model ids to the upstream OpenClaw config; if the user wasn't logged in
    # to most of them, those entries would surface as 404s downstream.
    catalog = load_model_catalog()
    return {
        'models': {
            'providers': {
                'algae': {
                    'baseUrl': base_url,
                    'apiKey': api_key,
                    'api': 'openai-completions',
                    'models': [entry.to_opentoken_dict() for entry in catalog],
                }
            }
        }
    }


def apply_algae_provider_patch(config_path: Path, patch: dict[str, object]) -> Path | None:
    existing: dict[str, object] = {}
    backup_path: Path | None = None

    if config_path.exists():
        raw = config_path.read_text(encoding='utf-8')
        try:
            parsed_existing = json.loads(raw)
        except json.JSONDecodeError as exc:
            # Don't crash on a corrupt upstream config — surface a clear error
            # so the user can repair it instead of seeing a raw stack trace.
            raise RuntimeError(
                f"Upstream config {config_path} is not valid JSON; refusing to "
                f"overwrite a corrupt file. Repair or remove it and retry. "
                f"({exc.__class__.__name__}: {exc})"
            ) from exc
        if isinstance(parsed_existing, dict):
            existing = parsed_existing
        timestamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
        backup_path = config_path.with_name(f'{config_path.name}.{timestamp}.bak')
        backup_path.write_text(raw, encoding='utf-8')

    merged = _merge_provider_patch(existing, patch)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    # The patch embeds the gateway API key in `providers.algae.apiKey`. Write
    # atomically (tmp + os.replace) so a crash mid-write can't truncate the
    # user's upstream config, and chmod 0600 so the secret isn't briefly
    # world-readable on a shared host.
    write_json_atomic(config_path, merged, sensitive=True)
    return backup_path


def _merge_provider_patch(existing: dict[str, object], patch: dict[str, object]) -> dict[str, object]:
    merged = copy.deepcopy(existing)
    models = merged.setdefault('models', {})
    if not isinstance(models, dict):
        models = {}
        merged['models'] = models

    providers = models.setdefault('providers', {})
    if not isinstance(providers, dict):
        providers = {}
        models['providers'] = providers

    patch_models = patch.get('models', {})
    if not isinstance(patch_models, dict):
        return merged

    patch_providers = patch_models.get('providers', {})
    if not isinstance(patch_providers, dict):
        return merged

    for provider_name, provider_config in patch_providers.items():
        providers[provider_name] = copy.deepcopy(provider_config)

    return merged
