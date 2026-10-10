from types import SimpleNamespace
import pytest
import codex_hybrid_control as c
from hybrid_diagnostics import compatibility


@pytest.fixture
def config(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'_home',lambda:tmp_path)
    monkeypatch.setattr(c,'get_user_api_key',lambda:None)
    c.bootstrap_codex_files()
    monkeypatch.setattr('hybrid_diagnostics.mcp_probe',lambda *a,**kw:{'version':c.APP_VERSION,'tool_count':4,'ping':True})
    return c.default_config_path()


def test_changed_desktop_version_triggers_new_compatibility_result(config,monkeypatch):
    import json
    c.write_json_atomic(c.control_dir()/'compatibility.json',{'cli_version':'codex 1.0','desktop_version':'OpenAI.Codex 1.0'})
    def run(command,**kw):
        if 'powershell.exe' in command:return SimpleNamespace(returncode=0,stdout=json.dumps({'Name':'OpenAI.Codex','Version':'2.0'}))
        return SimpleNamespace(returncode=0,stdout='codex 1.0' if '--version' in command else '--json --sandbox --skip-git-repo-check')
    monkeypatch.setattr(c,'run_bounded_process',run)
    before=config.read_bytes()
    result=compatibility(c,config)
    assert result['ok'] and result['version_changed']
    assert config.read_bytes()==before


def test_removed_cli_parameter_is_reported_as_incompatible(config,monkeypatch):
    monkeypatch.setattr(c,'run_bounded_process',lambda command,**kw:SimpleNamespace(returncode=0,stdout='codex 1.0' if '--version' in command else '{}'))
    result=compatibility(c,config)
    assert not result['ok']
    step=next(s for s in result['steps'] if s['name']=='Параметры запуска')
    assert step['status']=='error' and '--json' in step['detail']


def test_damaged_api_guard_is_reported_without_aborting_compatibility(config,monkeypatch):
    (c.control_dir()/'api-guard.json').write_text('[]')
    monkeypatch.setattr(c,'run_bounded_process',lambda command,**kw:SimpleNamespace(returncode=0,stdout='codex 1.0' if '--version' in command else '--json --sandbox --skip-git-repo-check'))
    result=compatibility(c,config)
    step=next(s for s in result['steps'] if s['name']=='Контроль активных API-запросов')
    assert step['status']=='error' and 'повреждены' in step['detail']
