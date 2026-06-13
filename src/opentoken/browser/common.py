from __future__ import annotations

from dataclasses import dataclass
import importlib
import importlib.metadata
import importlib.util
from pathlib import Path
import subprocess
import sys
from typing import Any


_INSTALL_HINT = (
    "Run `uv sync` to install Python dependencies, then "
    "`uv run python -m camoufox fetch` to install the Camoufox browser runtime."
)
_ZH_CN_LOCALES = ['zh-CN', 'zh', 'en-US', 'en']
_PROVIDER_LOCALE_OVERRIDES = {
    'deepseek': _ZH_CN_LOCALES,
    'qwen-cn': _ZH_CN_LOCALES,
    'doubao': _ZH_CN_LOCALES,
    'glm-cn': _ZH_CN_LOCALES,
    'mimo': _ZH_CN_LOCALES,
}


@dataclass(frozen=True)
class CamoufoxRuntimeStatus:
    package_installed: bool
    browser_installed: bool
    executable_path: str | None = None
    version: str | None = None
    install_hint: str = _INSTALL_HINT


class _CamoufoxPlaywrightSession:
    def __init__(self) -> None:
        self.chromium = self
        self._managers: list[Any] = []

    def __enter__(self) -> '_CamoufoxPlaywrightSession':
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        while self._managers:
            manager = self._managers.pop()
            try:
                manager.__exit__(exc_type, exc, tb)
            except Exception:
                continue

    def launch_persistent_context(self, user_data_dir: str | Path, **kwargs):
        provider = kwargs.pop('provider', None) or _infer_provider_from_user_data_dir(user_data_dir)
        headless = bool(kwargs.pop('headless', False))
        kwargs.pop('persistent_context', None)
        exclude_addons = _normalize_camoufox_exclude_addons(kwargs.pop('exclude_addons', []) or [])
        default_launch_options = _default_camoufox_launch_options(provider)

        camoufox = _resolve_camoufox_launcher()
        if camoufox is not None:
            launch_options = {
                'persistent_context': True,
                'user_data_dir': str(Path(user_data_dir)),
                'headless': headless,
                'exclude_addons': exclude_addons,
                **default_launch_options,
                **kwargs,
            }
            launch_options.setdefault('humanize', True)
            manager = camoufox(**launch_options)
            try:
                # __enter__ 可能因 profile lock / fetch corruption / OOM 抛异常 ——
                # 当时 manager 还没进 _managers,后续 cleanup 漏掉 → camoufox 子进
                # 程残留。在 __enter__ 失败时显式 __exit__ 触发 manager 自己的清理
                # 逻辑（如果有），并把异常透传上去让调用方知道启动失败。
                context = manager.__enter__()
            except BaseException:
                try:
                    manager.__exit__(None, None, None)
                except Exception:
                    pass
                raise
            self._managers.append(manager)
            return context

        fallback_browser_name = _resolve_playwright_fallback_browser_name()
        if fallback_browser_name is not None:
            sync_playwright = _import_playwright_sync_api()
            manager = sync_playwright()
            playwright = manager.__enter__()
            try:
                # 'chrome' is not a Playwright BrowserType — it's a Chromium
                # *channel* pointing at the user's locally-installed Chrome.
                # Route it through chromium with channel='chrome' (and an
                # explicit executable_path discovered on the host) so users
                # get their real browser, not the Playwright-bundled one.
                if fallback_browser_name == 'chrome':
                    browser_type = playwright.chromium
                    is_system_chrome = True
                else:
                    browser_type = getattr(playwright, fallback_browser_name)
                    is_system_chrome = False
                fallback_launch_options = {
                    'headless': headless,
                    **kwargs,
                }
                locale = default_launch_options.get('locale')
                if isinstance(locale, list):
                    locale = next((str(item).strip() for item in locale if str(item).strip()), '')
                elif not isinstance(locale, str):
                    locale = ''
                locale = locale.strip()
                if locale:
                    fallback_launch_options['locale'] = locale
                if is_system_chrome:
                    fallback_launch_options['channel'] = 'chrome'
                    chrome_path = _discover_system_chrome_executable()
                    if chrome_path:
                        fallback_launch_options['executable_path'] = chrome_path
                else:
                    executable_path = getattr(browser_type, 'executable_path', None)
                    if isinstance(executable_path, str) and executable_path.strip():
                        fallback_launch_options.setdefault('executable_path', executable_path)
                context = browser_type.launch_persistent_context(
                    str(Path(user_data_dir)),
                    **fallback_launch_options,
                )
            except Exception:
                try:
                    manager.__exit__(None, None, None)
                except Exception:
                    pass
                raise
            self._managers.append(manager)
            return context

        status = probe_camoufox_runtime()
        raise RuntimeError(
            'Camoufox browser runtime is not installed and no fallback browser is available '
            '(neither a system-installed Chrome nor a Playwright-bundled browser). '
            f'{status.install_hint}'
        )


class _CamoufoxSyncPlaywrightFactory:
    def __call__(self) -> _CamoufoxPlaywrightSession:
        return _CamoufoxPlaywrightSession()


_SYNC_PLAYWRIGHT = _CamoufoxSyncPlaywrightFactory()


def prepare_browser_state_dir(state_dir: Path, provider: str) -> Path:
    browser_state_dir = state_dir / 'browser' / provider
    browser_state_dir.mkdir(parents=True, exist_ok=True)
    return browser_state_dir


def build_cookie_string(cookies: list[dict[str, Any]]) -> str:
    return '; '.join(
        f"{cookie['name']}={cookie['value']}"
        for cookie in cookies
        if cookie.get('name') and cookie.get('value') is not None
    )


def probe_camoufox_runtime() -> CamoufoxRuntimeStatus:
    spec = importlib.util.find_spec('camoufox')
    if spec is None:
        return CamoufoxRuntimeStatus(
            package_installed=False,
            browser_installed=False,
            install_hint=_INSTALL_HINT,
        )

    version = _resolve_camoufox_version()

    executable_path = _discover_camoufox_executable()
    return CamoufoxRuntimeStatus(
        package_installed=True,
        browser_installed=executable_path is not None,
        executable_path=executable_path,
        version=version,
        install_hint=_INSTALL_HINT,
    )


def require_camoufox():
    status = ensure_camoufox_runtime()
    try:
        from camoufox.sync_api import Camoufox
    except ImportError as exc:
        raise RuntimeError(f'Camoufox is required for browser login. {status.install_hint}') from exc
    return Camoufox


def ensure_camoufox_runtime() -> CamoufoxRuntimeStatus:
    status = probe_camoufox_runtime()
    if not status.package_installed:
        raise RuntimeError(f'Camoufox is required for browser login. {status.install_hint}')
    if not status.browser_installed:
        print(
            'Camoufox browser runtime is missing. Attempting automatic install via `python -m camoufox fetch`...',
            file=sys.stderr,
        )
        _run_camoufox_fetch()
        status = probe_camoufox_runtime()
        if not status.browser_installed:
            raise RuntimeError(f'Camoufox browser runtime is not installed. {status.install_hint}')
    return status


def require_sync_playwright() -> _CamoufoxSyncPlaywrightFactory:
    return _SYNC_PLAYWRIGHT


def _run_camoufox_fetch() -> None:
    commands = [
        [sys.executable, '-m', 'camoufox', 'fetch'],
        ['python3', '-m', 'camoufox', 'fetch'],
    ]
    for command in commands:
        try:
            result = subprocess.run(
                command,
                check=False,
                timeout=1800,
            )
        except Exception:
            continue
        if result.returncode == 0:
            return


def _resolve_camoufox_launcher():
    status = probe_camoufox_runtime()
    if not status.package_installed or not status.browser_installed:
        return None
    try:
        from camoufox.sync_api import Camoufox
    except ImportError:
        return None
    return Camoufox


def _import_playwright_sync_api():
    from playwright.sync_api import sync_playwright

    return sync_playwright


_SYSTEM_CHROME_PATHS = {
    'darwin': [
        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        '/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta',
        '/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
    ],
    'linux': [
        '/usr/bin/google-chrome',
        '/usr/bin/google-chrome-stable',
        '/usr/bin/chrome',
        '/opt/google/chrome/google-chrome',
        '/opt/google/chrome/chrome',
        '/snap/bin/chromium',
        '/usr/bin/chromium',
        '/usr/bin/chromium-browser',
    ],
    'win32': [
        r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        # WSL: access Windows-side Chrome via /mnt/c
        '/mnt/c/Program Files/Google/Chrome/Application/chrome.exe',
        '/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    ],
}


def _discover_system_chrome_executable() -> str | None:
    """Find a system-installed Google Chrome. Returns absolute path or None.

    On WSL we also check /mnt/c paths so Linux-WSL invocations can drive the
    Windows-side Chrome the user already uses."""
    candidates: list[str] = []
    if sys.platform.startswith('darwin'):
        candidates.extend(_SYSTEM_CHROME_PATHS['darwin'])
    elif sys.platform.startswith('win'):
        candidates.extend(_SYSTEM_CHROME_PATHS['win32'])
    elif sys.platform.startswith('linux'):
        candidates.extend(_SYSTEM_CHROME_PATHS['linux'])
        # WSL: prefer Linux-side Chrome if installed; otherwise fall through
        # to Windows-side Chrome under /mnt/c.
        candidates.extend(_SYSTEM_CHROME_PATHS['win32'])

    for candidate in candidates:
        try:
            if Path(candidate).exists():
                return candidate
        except Exception:
            continue
    return None


def _resolve_playwright_fallback_browser_name() -> str | None:
    try:
        sync_playwright = _import_playwright_sync_api()
    except Exception:
        return None

    # Prefer system-installed Chrome (`channel='chrome'`) so the user gets
    # their real browser profile + extensions instead of a bare Playwright
    # chromium that triggers more bot checks.
    if _discover_system_chrome_executable() is not None:
        return 'chrome'

    try:
        with sync_playwright() as playwright:
            for candidate in ('firefox', 'chromium'):
                browser_type = getattr(playwright, candidate, None)
                executable_path = getattr(browser_type, 'executable_path', None)
                if isinstance(executable_path, str) and executable_path.strip():
                    if Path(executable_path).exists():
                        return candidate
    except Exception:
        return None
    return None


def _discover_camoufox_executable() -> str | None:
    try:
        pkgman = importlib.import_module('camoufox.pkgman')
    except Exception:
        pkgman = None

    if pkgman is not None:
        camoufox_path = getattr(pkgman, 'camoufox_path', None)
        install_dir = None
        if callable(camoufox_path):
            try:
                install_dir = camoufox_path(download_if_missing=False)
            except Exception:
                install_dir = None
        if install_dir is None:
            install_dir = getattr(pkgman, 'INSTALL_DIR', None)

        launch_files = getattr(pkgman, 'LAUNCH_FILE', None)
        os_name = getattr(pkgman, 'OS_NAME', None)
        if install_dir is not None and isinstance(launch_files, dict) and isinstance(os_name, str):
            launch_file = launch_files.get(os_name)
            if isinstance(launch_file, str) and launch_file.strip():
                install_path = Path(install_dir).expanduser()
                if os_name == 'mac':
                    candidate = (
                        install_path / 'Camoufox.app' / 'Contents' / 'Resources' / launch_file
                    ).resolve()
                else:
                    candidate = (install_path / launch_file).resolve()
                if candidate.exists():
                    return str(candidate)
    return None


def _resolve_camoufox_version() -> str | None:
    try:
        return importlib.metadata.version('camoufox')
    except Exception:
        pass

    try:
        module = importlib.import_module('camoufox')
    except Exception:
        return None

    version = getattr(module, '__version__', None)
    if isinstance(version, str) and version.strip():
        return version.strip()
    return None




def _normalize_camoufox_exclude_addons(exclude_addons: list[Any]) -> list[Any]:
    normalized: list[Any] = []
    ubo_addon = _resolve_camoufox_ubo_addon()

    for addon in exclude_addons:
        candidate = ubo_addon if addon == 'UBO' or getattr(addon, 'name', None) == 'UBO' else addon
        if candidate not in normalized:
            normalized.append(candidate)

    if ubo_addon is not None and ubo_addon not in normalized:
        normalized.append(ubo_addon)
    return normalized


def _default_camoufox_launch_options(provider: str | None) -> dict[str, Any]:
    launch_options: dict[str, Any] = {}
    target_os = _host_camoufox_os()
    if target_os is not None:
        launch_options['os'] = target_os
    locale = _PROVIDER_LOCALE_OVERRIDES.get(provider or '')
    if locale is not None:
        launch_options['locale'] = list(locale)
    return launch_options


def _infer_provider_from_user_data_dir(user_data_dir: str | Path) -> str | None:
    name = Path(user_data_dir).name.strip()
    return name or None


def _host_camoufox_os() -> str | None:
    if sys.platform.startswith('darwin'):
        return 'macos'
    if sys.platform.startswith('linux'):
        return 'linux'
    if sys.platform.startswith('win'):
        return 'windows'
    return None


def _resolve_camoufox_ubo_addon() -> Any:
    try:
        from camoufox.addons import DefaultAddons
        return DefaultAddons.UBO
    except Exception:
        return None
