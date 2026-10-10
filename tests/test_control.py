import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import codex_hybrid_control as c


def test_patch_table_preserves_unknown():
    src = '''model_provider = "openai"\nmodel = "x"\n\n[model_providers.funpay]\nname = "Old"\ncustom = "keep"\n\n[plugins]\nenabled = true\n'''
    out = c.patch_table_keys(src, "model_providers.funpay", c.provider_values())
    parsed = c.validate_toml(out)
    assert parsed["model_providers"]["funpay"]["base_url"] == "https://tokify.sale/v1"
    assert parsed["model_providers"]["funpay"]["custom"] == "keep"
    assert parsed["plugins"]["enabled"] is True


def test_bootstrap_and_modes_no_secret_in_files():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        old_home = c._home
        old_config = c.default_config_path
        old_catalog = c.default_catalog_path
        old_codex = c.codex_dir
        try:
            c._home = lambda: home
            c.codex_dir = lambda: home / ".codex"
            c.default_config_path = lambda: home / ".codex" / "config.toml"
            c.default_catalog_path = lambda: home / ".codex" / "funpay-models.json"
            result = c.bootstrap_codex_files()
            assert c.default_config_path().exists()
            assert c.default_catalog_path().exists()
            for name in c.WORKER_PROFILES:
                assert (c.codex_dir() / f"{name}.config.toml").exists()

            _backup, parsed = c.apply_mode(c.default_config_path(), "api", "claude-opus-5.5", "high", "api_only")
            assert parsed["model_provider"] == "funpay"
            assert parsed["model"] == "claude-opus-5.5"
            assert parsed["agents"]["enabled"] is False

            _backup, parsed = c.apply_mode(c.default_config_path(), "official", None, "high", "api_only")
            assert parsed["model_provider"] == "openai"
            assert parsed["model"] == "gpt-6.1-sol"
            assert parsed["agents"]["enabled"] is False
            assert "model_catalog_json" not in parsed

            _backup, parsed = c.apply_mode(c.default_config_path(), "official", None, "high", "hybrid")
            assert parsed["agents"]["enabled"] is True

            fake_secret = "sk-THIS-MUST-NEVER-BE-WRITTEN"
            for path in c.codex_dir().rglob("*"):
                if path.is_file():
                    assert fake_secret not in path.read_text(encoding="utf-8", errors="ignore")
        finally:
            c._home = old_home
            c.default_config_path = old_config
            c.default_catalog_path = old_catalog
            c.codex_dir = old_codex


def test_existing_worker_profile_is_preserved():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        home.mkdir(parents=True, exist_ok=True)
        custom = home / "opus.config.toml"
        custom.write_text('model_provider = "something"\nmodel = "custom-model"\n', encoding="utf-8")
        result = c.ensure_worker_profiles(home, home / "catalog.json")
        assert result["opus"] == "existing"
        assert "custom-model" in custom.read_text(encoding="utf-8")


def test_pick_packaged_codex_target():
    one = [{"name": "Codex", "aumid": "OpenAI.Codex_x!App", "package": "OpenAI.Codex", "source": "appx"}]
    picked = c._pick_packaged_codex_target(one)
    assert picked and picked["aumid"] == "OpenAI.Codex_x!App"

    ambiguous = [
        {"name": "Codex A", "aumid": "A!App", "package": "", "source": "startapps"},
        {"name": "Codex B", "aumid": "B!App", "package": "", "source": "startapps"},
    ]
    assert c._pick_packaged_codex_target(ambiguous) is None


def test_normalize_key_info_and_format_tokens():
    raw = {
        "limits": {"rpm": 60, "rpd": 1000, "win5h_tokens": 5000000},
        "usage": {"today_requests": 12, "total_requests": 345, "total_tokens": 2500000, "win5h_tokens": 123456},
        "quota": {"total": 1100000000, "used": 52500000, "remaining": 1047500000},
    }
    d = c.normalize_key_info(raw)
    assert d["quota_remaining"] == 1047500000
    assert round(d["quota_used_pct"], 3) == round(52500000 / 1100000000 * 100, 3)
    assert d["rpm_limit"] == 60
    assert c.format_tokens(1047500000) == "1.05B"
    assert c.format_tokens(2500000) == "2.5M"



def test_generated_worker_profiles_disable_native_agents():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        catalog = home / "catalog.json"
        catalog.write_text("{}", encoding="utf-8")
        result = c.ensure_worker_profiles(home, catalog)
        for name in c.WORKER_PROFILES:
            assert result[name] == "created"
            parsed = c.validate_toml((home / f"{name}.config.toml").read_text(encoding="utf-8"))
            assert parsed["model_provider"] == "funpay"
            assert parsed["agents"]["enabled"] is False


def test_worker_profile_health_rejects_wrong_provider_and_native_agents():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        p = home / "opus.config.toml"
        p.write_text('model_provider = "openai"\nmodel = "claude-opus-5.5"\n[agents]\nenabled = true\n', encoding="utf-8")
        health = c.inspect_worker_profile(home, "opus")
        assert health["ready"] is False
        assert "provider=openai" in health["reason"]
        assert "native-agents-enabled" in health["reason"]


def test_generated_worker_profile_health_is_ready():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        catalog = home / "catalog.json"
        catalog.write_text("{}", encoding="utf-8")
        c.ensure_worker_profiles(home, catalog)
        for name in c.WORKER_PROFILES:
            health = c.inspect_worker_profile(home, name)
            assert health["ready"] is True
            assert health["provider"] == "funpay"
            assert health["native_agents_enabled"] is False


def test_current_root_info_reports_native_agent_state():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "config.toml"
        p.write_text('model_provider = "openai"\nmodel = "gpt-6.1-sol"\n[agents]\nenabled = false\n', encoding="utf-8")
        info = c.current_root_info(p)
        assert info["native_agents_enabled"] is False
        p.write_text('model_provider = "openai"\nmodel = "gpt-6.1-sol"\n', encoding="utf-8")
        info = c.current_root_info(p)
        assert info["native_agents_enabled"] is True


def test_computer_mcp_install_and_remove_preserves_other_tables():
    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td) / "config.toml"
        cfg.write_text('model_provider = "openai"\nmodel = "gpt-6.1-sol"\n\n[plugins]\nenabled = true\n', encoding="utf-8")
        c.install_computer_mcp(cfg)
        parsed = c.validate_toml(cfg.read_text(encoding="utf-8"))
        assert "hybridComputer" in parsed["mcp_servers"]
        assert parsed["plugins"]["enabled"] is True
        c.uninstall_computer_mcp(cfg)
        parsed = c.validate_toml(cfg.read_text(encoding="utf-8"))
        assert "hybridComputer" not in parsed.get("mcp_servers", {})
        assert parsed["plugins"]["enabled"] is True


def test_computer_policy_defaults_and_save():
    with tempfile.TemporaryDirectory() as td:
        old_codex = c.codex_dir
        try:
            c.codex_dir = lambda: Path(td) / ".codex"
            p = c.computer_policy()
            assert p["enabled"] is False
            assert p["allow_input"] is False
            c.save_computer_policy({"enabled": True, "allow_screenshot": True, "allow_input": True, "allow_launch": False})
            p = c.computer_policy()
            assert p["enabled"] is True and p["allow_input"] is True
        finally:
            c.codex_dir = old_codex


def test_refresh_worker_registry_marks_dead_worker():
    with tempfile.TemporaryDirectory() as td:
        old_codex = c.codex_dir
        try:
            c.codex_dir = lambda: Path(td) / ".codex"
            c._save_workers([{"id": "x", "pid": 999999999, "status": "RUNNING", "log": ""}])
            rows = c.refresh_worker_registry()
            assert rows[0]["status"] == "EXITED"
        finally:
            c.codex_dir = old_codex
if __name__ == "__main__":
    test_patch_table_preserves_unknown()
    test_bootstrap_and_modes_no_secret_in_files()
    test_existing_worker_profile_is_preserved()
    test_pick_packaged_codex_target()
    test_normalize_key_info_and_format_tokens()
    test_generated_worker_profiles_disable_native_agents()
    test_worker_profile_health_rejects_wrong_provider_and_native_agents()
    test_generated_worker_profile_health_is_ready()
    test_current_root_info_reports_native_agent_state()
    test_computer_mcp_install_and_remove_preserves_other_tables()
    test_computer_policy_defaults_and_save()
    test_refresh_worker_registry_marks_dead_worker()
    print("OK")



def test_worker_mcp_install_and_instructions_preserve_user_content():
    with tempfile.TemporaryDirectory() as td:
        old_codex = c.codex_dir
        try:
            home = Path(td) / ".codex"
            home.mkdir(parents=True, exist_ok=True)
            c.codex_dir = lambda: home
            cfg = home / "config.toml"
            cfg.write_text('model_provider = "openai"\nmodel = "gpt-6.1-sol"\n\n[plugins]\nenabled = true\n', encoding="utf-8")
            agents = home / "AGENTS.md"
            agents.write_text("# Мои инструкции\nНе трогай этот текст.\n", encoding="utf-8")

            changed, _backup, parsed = c.install_worker_mcp(cfg)
            assert changed is True
            assert "hybridWorkers" in parsed["mcp_servers"]
            assert parsed["mcp_servers"]["hybridWorkers"]["enabled"] is True
            assert "enabled_tools" not in parsed["mcp_servers"]["hybridWorkers"]
            assert parsed["mcp_servers"]["hybridWorkers"]["tool_timeout_sec"] == 120
            changed2, path = c.install_worker_instructions()
            assert changed2 is True
            text = path.read_text(encoding="utf-8")
            assert "# Мои инструкции" in text
            assert c.WORKER_INSTRUCTIONS_BEGIN in text
            assert "api_worker_spawn" in text
            changed3, _ = c.install_worker_instructions()
            assert changed3 is False
            assert c.worker_mcp_installed(cfg) is True
            assert c.worker_instructions_installed() is True
        finally:
            c.codex_dir = old_codex


def test_worker_mcp_tools_and_list_call():
    names = {item["name"] for item in c._worker_tools()}
    assert names == {"api_worker_spawn", "api_worker_list", "api_worker_result", "api_worker_stop"}
    old_refresh = c.refresh_worker_registry
    try:
        c.refresh_worker_registry = lambda: [
            {"id": "opus-x", "profile": "opus", "model_selector": "claude-opus-5.5", "project": "/tmp/p", "status": "RUNNING", "last_message": ""}
        ]
        payload = json.loads(c._worker_call("api_worker_list", {}))
        assert payload[0]["id"] == "opus-x"
        assert payload[0]["profile"] == "opus"
    finally:
        c.refresh_worker_registry = old_refresh


def test_worker_profiles_disable_worker_and_computer_mcp():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        catalog = home / "catalog.json"
        catalog.write_text("{}", encoding="utf-8")
        c.ensure_worker_profiles(home, catalog)
        for name in c.WORKER_PROFILES:
            parsed = c.validate_toml((home / f"{name}.config.toml").read_text(encoding="utf-8"))
            assert "mcp_servers" not in parsed or not parsed.get("mcp_servers")
            health = c.inspect_worker_profile(home, name)
            assert health["ready"] is True
            assert health["worker_mcp_disabled"] is True
            assert health["computer_mcp_disabled"] is True


def test_explicit_repair_migrates_legacy_worker_profiles_and_preserves_custom_keys():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        catalog = home / "catalog.json"
        catalog.write_text("{}", encoding="utf-8")
        for name, cfg in c.WORKER_PROFILES.items():
            p = home / f"{name}.config.toml"
            p.write_text(
                f'model_provider = "funpay"\nmodel = "{cfg["model"]}"\ncustom_root = "keep"\n\n'
                '[agents]\nenabled = true\ncustom_agent_key = "keep"\n\n'
                '[mcp_servers.hybridWorkers]\nenabled = true\n\n'
                '[mcp_servers.hybridComputer]\nenabled = true\n\n'
                '[plugins]\nenabled = true\n',
                encoding="utf-8",
            )
        result = c.repair_worker_profiles(home, catalog)
        assert set(result) == set(c.WORKER_PROFILES)
        for name in c.WORKER_PROFILES:
            health = c.inspect_worker_profile(home, name)
            assert health["ready"] is True, health
            parsed = c.validate_toml((home / f"{name}.config.toml").read_text(encoding="utf-8"))
            assert parsed["custom_root"] == "keep"
            assert parsed["agents"]["custom_agent_key"] == "keep"
            assert parsed["plugins"]["enabled"] is True
            assert parsed["agents"]["enabled"] is False
            assert parsed["mcp_servers"]["hybridWorkers"]["enabled"] is False
            assert parsed["mcp_servers"]["hybridComputer"]["enabled"] is False
        backups = list((home / "hybrid_control_backups").glob("*.toml"))
        assert len(backups) == 3


def test_enforce_api_only_root_policy_preserves_provider_model_and_unknown_sections():
    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td) / "config.toml"
        cfg.write_text(
            'model_provider = "openai"\nmodel = "gpt-6.1-sol"\ncustom_root = "keep"\n\n'
            '[agents]\nenabled = true\nother = "keep"\n\n'
            '[plugins]\nenabled = true\n',
            encoding="utf-8",
        )
        changed, backup = c.enforce_api_only_root_policy(cfg)
        assert changed is True
        assert backup is not None and backup.exists()
        parsed = c.validate_toml(cfg.read_text(encoding="utf-8"))
        assert parsed["model_provider"] == "openai"
        assert parsed["model"] == "gpt-6.1-sol"
        assert parsed["custom_root"] == "keep"
        assert parsed["agents"]["enabled"] is False
        assert parsed["agents"]["other"] == "keep"
        assert parsed["plugins"]["enabled"] is True


def test_api_mode_forces_native_agents_off_even_if_hybrid_requested():
    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td) / "config.toml"
        old_catalog = c.default_catalog_path
        try:
            c.default_catalog_path = lambda: Path(td) / "catalog.json"
            c.default_catalog_path().write_text("{}", encoding="utf-8")
            cfg.write_text(c.minimal_config_text(), encoding="utf-8")
            _backup, parsed = c.apply_mode(cfg, "api", "gpt-6-astra", "high", "hybrid")
            assert parsed["model_provider"] == "funpay"
            assert parsed["agents"]["enabled"] is False
        finally:
            c.default_catalog_path = old_catalog


def test_computer_tool_surface_and_mcp_config_are_complete():
    names = {item["name"] for item in c._computer_tools()}
    assert names == {
        "computer_status", "computer_list_windows", "computer_focus_window", "computer_screenshot",
        "computer_mouse_move", "computer_click", "computer_drag", "computer_scroll", "computer_type",
        "computer_hotkey", "computer_key", "computer_launch_app", "computer_wait", "computer_act",
        "browser_fetch",
        "computer_elements", "computer_element_action", "browser_control",
        "computer_wait_for", "computer_action_status",
    }
    act = next(x for x in c._computer_tools() if x["name"] == "computer_act")
    assert act["inputSchema"]["properties"]["actions"]["maxItems"] == 20

    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td) / "config.toml"
        cfg.write_text(c.minimal_config_text(), encoding="utf-8")
        c.install_computer_mcp(cfg)
        parsed = c.validate_toml(cfg.read_text(encoding="utf-8"))
        item = parsed["mcp_servers"]["hybridComputer"]
        assert item["enabled"] is True
        assert item["startup_timeout_sec"] == 20
        assert item["tool_timeout_sec"] == 120
        assert "default_tools_approval_mode" not in item
        assert "enabled_tools" not in item
        assert c.computer_mcp_installed(cfg) is True


def test_computer_instructions_preserve_user_agents_content():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "AGENTS.md"
        p.write_text("# USER RULES\nkeep-this\n", encoding="utf-8")
        changed, _ = c.install_computer_instructions(p)
        assert changed is True
        text = p.read_text(encoding="utf-8")
        assert "keep-this" in text
        assert c.COMPUTER_INSTRUCTIONS_BEGIN in text
        assert "computer_screenshot" in text
        changed2, _ = c.install_computer_instructions(p)
        assert changed2 is False
        assert c.computer_instructions_installed(p) is True


def test_multi_monitor_negative_origin_coordinate_translation():
    old_frame = c._COMPUTER_SESSION.get("frame")
    try:
        c._COMPUTER_SESSION["frame"] = {
            "origin_x": -1920, "origin_y": -200, "width": 3840, "height": 1400,
        }
        assert c._translate_point(0, 0, "screenshot") == (-1920, -200)
        assert c._translate_point(1920, 200, "screenshot") == (0, 0)
        assert c._translate_point(10, 20, "desktop") == (10, 20)
        try:
            c._translate_point(5000, 1, "screenshot")
            assert False, "out-of-frame coordinates must fail"
        except ValueError:
            pass
    finally:
        c._COMPUTER_SESSION["frame"] = old_frame


def test_screenshot_content_returns_frame_metadata_and_mixed_mcp_content():
    with tempfile.TemporaryDirectory() as td:
        old_codex = c.codex_dir
        old_bounds = c._virtual_screen_bounds
        old_resolve = c._resolve_window
        old_capture = c._capture_region_png
        old_fg = c._foreground_window
        try:
            c.codex_dir = lambda: Path(td) / ".codex"
            c.enable_full_api_computer_policy()
            c._virtual_screen_bounds = lambda: {
                "left": -100, "top": -50, "right": 900, "bottom": 750, "width": 1000, "height": 800,
            }
            c._resolve_window = lambda args: {
                "hwnd": 7, "title": "Test", "minimized": False,
                "rect": {"left": -10, "top": 5, "right": 790, "bottom": 605, "width": 800, "height": 600},
            } if args.get("hwnd") == 7 else None
            c._capture_region_png = lambda bounds: b"\x89PNG\r\n\x1a\n" + (b"x" * 128)
            c._foreground_window = lambda: {"hwnd": 7, "title": "Test"}
            content = c._screenshot_content({"hwnd": 7})
            assert content[0]["type"] == "text"
            meta = json.loads(content[0]["text"])
            assert meta["frame"]["origin_x"] == -10
            assert meta["frame"]["width"] == 800
            assert meta["frame"]["scope"]["kind"] == "window"
            assert content[1]["type"] == "image"
            assert content[1]["mimeType"] == "image/png"
            mcp = c._mcp_result(4, content, False)
            assert mcp["result"]["content"] == content
            assert c._translate_point(10, 10, "screenshot") == (0, 15)
        finally:
            c.codex_dir = old_codex
            c._virtual_screen_bounds = old_bounds
            c._resolve_window = old_resolve
            c._capture_region_png = old_capture
            c._foreground_window = old_fg


def test_unicode_input_struct_and_surrogate_units():
    import ctypes
    assert ctypes.sizeof(c._INPUT) in {28, 40}
    units = c._unicode_code_units("AЯ😀")
    assert units[0] == ord("A")
    assert units[1] == ord("Я")
    assert len(units) == 4
    event = c._INPUT()
    event.type = 1
    event.ki = c._KEYBDINPUT(0, units[1], 0x0004, 0, 0)
    assert event.ki.wScan == ord("Я")
    assert event.ki.dwFlags & 0x0004


def test_computer_act_rejects_excessive_wait_budget_before_execution():
    with tempfile.TemporaryDirectory() as td:
        old_codex = c.codex_dir
        try:
            c.codex_dir = lambda: Path(td) / ".codex"
            c.enable_full_api_computer_policy()
            try:
                c._computer_call("computer_act", {"actions": [
                    {"type": "wait", "seconds": 30},
                    {"type": "wait", "seconds": 20},
                ]})
                assert False, "overlong batch must be rejected"
            except ValueError as exc:
                assert "45" in str(exc)
        finally:
            c.codex_dir = old_codex


def test_hybrid_chat_auto_never_routes_official_when_root_is_api():
    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td) / "config.toml"
        old_catalog = c.default_catalog_path
        try:
            c.default_catalog_path = lambda: Path(td) / "catalog.json"
            c.default_catalog_path().write_text("{}", encoding="utf-8")
            cfg.write_text(c.minimal_config_text(), encoding="utf-8")
            c.apply_mode(cfg, "api", "gpt-6-astra", "high", "api_only")
            route = c.hybrid_chat_auto_route(cfg, "claude-opus-5.5", "medium")
            assert route["mode"] == "auto_api"
            assert route["model"] == "gpt-6-astra"
            assert route["official_allowed"] is False
        finally:
            c.default_catalog_path = old_catalog


def test_prepare_api_autonomy_builds_consistent_stack():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td) / ".codex"
        home.mkdir(parents=True)
        old_codex = c.codex_dir
        old_cfg = c.default_config_path
        old_catalog = c.default_catalog_path
        old_present = c.user_api_key_present
        try:
            c.codex_dir = lambda: home
            c.default_config_path = lambda: home / "config.toml"
            c.default_catalog_path = lambda: home / "funpay-models.json"
            c.user_api_key_present = lambda: True
            c.ensure_provider_config(c.default_config_path())
            c.seed_catalog(c.default_catalog_path())
            c.apply_mode(c.default_config_path(), "api", "gpt-6-astra", "high", "hybrid")
            health = c.prepare_api_autonomy(c.default_config_path())
            assert health["ready"] is True, health
            parsed = c.validate_toml(c.default_config_path().read_text(encoding="utf-8"))
            assert parsed["model_provider"] == "funpay"
            assert parsed["agents"]["enabled"] is False
            assert parsed["mcp_servers"]["hybridWorkers"]["enabled"] is True
            assert parsed["mcp_servers"]["hybridComputer"]["enabled"] is True
            policy = c.computer_policy()
            assert policy == {"enabled": True, "allow_screenshot": True, "allow_input": True, "allow_launch": True, "control_mode": "auto"}
            assert c.worker_instructions_installed() is True
            assert c.computer_instructions_installed() is True
            for name in c.WORKER_PROFILES:
                assert c.inspect_worker_profile(home, name)["ready"] is True
        finally:
            c.codex_dir = old_codex
            c.default_config_path = old_cfg
            c.default_catalog_path = old_catalog
            c.user_api_key_present = old_present


def test_computer_mcp_protocol_lists_all_tools_end_to_end():
    import subprocess
    req = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
        "",
    ])
    cp = subprocess.run([sys.executable, str(ROOT / "codex_hybrid_control.py"), "--mcp-computer"], input=req, text=True, capture_output=True, timeout=10)
    assert cp.returncode == 0, cp.stderr
    rows = [json.loads(x) for x in cp.stdout.splitlines() if x.strip()]
    assert rows[0]["result"]["serverInfo"]["name"] == "Codex Hybrid Local Computer"
    names = {x["name"] for x in rows[1]["result"]["tools"]}
    assert set(c.computer_tool_names()) == names


def test_api_computer_model_e2e_pins_funpay_and_refuses_official():
    class FakeCP:
        returncode = 0
        stderr = ""
        stdout = "\n".join([
            json.dumps({"type": "item.started", "item": {"type": "mcp_tool_call", "tool": "computer_status"}}),
            json.dumps({"type": "item.started", "item": {"type": "mcp_tool_call", "tool": "computer_screenshot"}}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "API_COMPUTER_E2E_OK"}}),
        ])

    with tempfile.TemporaryDirectory() as td:
        home = Path(td) / ".codex"
        home.mkdir(parents=True)
        cfg = home / "config.toml"
        old_codex = c.codex_dir
        old_catalog = c.default_catalog_path
        old_present = c.user_api_key_present
        old_get = c.get_user_api_key
        old_cmd = c.codex_command
        old_run = c.subprocess.run
        captured = {}
        try:
            c.codex_dir = lambda: home
            c.default_catalog_path = lambda: home / "catalog.json"
            c.default_catalog_path().write_text("{}", encoding="utf-8")
            c.user_api_key_present = lambda: True
            c.get_user_api_key = lambda: "fake-api-key"
            c.codex_command = lambda: "codex-test"
            cfg.write_text(c.minimal_config_text(), encoding="utf-8")
            c.apply_mode(cfg, "api", "gpt-6-astra", "high", "api_only")
            c.install_computer_mcp(cfg)
            c.enable_full_api_computer_policy()
            def fake_run(cmd, **kwargs):
                captured["cmd"] = list(cmd)
                captured["env"] = dict(kwargs.get("env") or {})
                return FakeCP()
            c.subprocess.run = fake_run
            result = c.api_computer_model_e2e(cfg, project=Path(td), timeout=60)
            assert result["ok"] is True, result
            joined = " ".join(captured["cmd"])
            assert 'model_provider="funpay"' in joined
            assert 'model_provider="openai"' not in joined
            assert "agents.enabled=false" in captured["cmd"]
            assert captured["env"][c.API_ENV_KEY] == "fake-api-key"

            c.apply_mode(cfg, "official", None, "high", "api_only")
            refused = c.api_computer_model_e2e(cfg, project=Path(td), timeout=60)
            assert refused == {"ok": False, "error": "root-not-api-provider"}
        finally:
            c.codex_dir = old_codex
            c.default_catalog_path = old_catalog
            c.user_api_key_present = old_present
            c.get_user_api_key = old_get
            c.codex_command = old_cmd
            c.subprocess.run = old_run


def test_jsonl_tool_evidence_ignores_prompt_text_and_requires_tool_event():
    raw = "\n".join([
        json.dumps({"type": "user_message", "text": "please call computer_status and computer_screenshot"}),
        json.dumps({"type": "item.started", "item": {"type": "mcp_tool_call", "tool": "computer_status"}}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "computer_screenshot"}}),
    ])
    assert c._jsonl_tool_evidence(raw) == {"computer_status"}
