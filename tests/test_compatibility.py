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


def test_saved_proxy_fix_with_old_process_is_reported_as_local_issue(config,monkeypatch,tmp_path):
    import json
    import hybrid_diagnostics as diagnostics
    monkeypatch.setattr(c,'run_bounded_process',lambda command,**kw:SimpleNamespace(returncode=0,stdout='codex 1.0' if '--version' in command else '--json --sandbox --skip-git-repo-check'))
    monkeypatch.setattr('hybrid_proxy.read_user_bypass',lambda:'127.0.0.1,localhost,::1')
    monkeypatch.setenv('HTTP_PROXY','http://private-user:private-password@proxy.example:9')
    monkeypatch.setenv('NO_PROXY','');monkeypatch.setenv('no_proxy','')
    result=compatibility(c,config)
    step=next(s for s in result['steps'] if s['name']=='Локальный маршрут и прокси')
    assert step['status']=='warning' and step['restart_required']
    assert 'перезапустите' in step['detail']
    report=tmp_path/'report.json'
    diagnostics.export_report(c,config,report)
    data=json.loads(report.read_text(encoding='utf-8'))
    assert data['problem_layers']['local_connection']
    assert not data['problem_layers']['provider']
    assert 'private-password' not in report.read_text(encoding='utf-8')


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


@pytest.mark.parametrize('mismatch',['port','access','missing','remote','match'])
def test_healthy_gateway_cannot_hide_outdated_provider_route(config,monkeypatch,mismatch):
    import json
    import hybrid_api_guard as guard
    settings={'enabled':True,'port':12345,'access':'local-test-secret'}
    c.write_json_atomic(c.control_dir()/'api-guard.json',settings)
    monkeypatch.setattr(guard,'healthy',lambda settings:True)
    monkeypatch.setattr(c,'run_bounded_process',lambda command,**kw:SimpleNamespace(returncode=0,stdout='codex 1.0' if '--version' in command else '--json --sandbox --skip-git-repo-check'))
    routes={'port':'http://127.0.0.1:12346/local-test-secret/v1',
            'access':'http://127.0.0.1:12345/outdated-secret/v1','missing':'',
            'remote':'https://example.com/v1','match':'http://127.0.0.1:12345/local-test-secret/v1/'}
    text=config.read_text(encoding='utf-8')
    text=c.patch_table_keys(text,'model_providers.funpay',{'base_url':c._toml_string(routes[mismatch])})
    config.write_text(text,encoding='utf-8')
    before=config.read_bytes()
    result=compatibility(c,config)
    step=next(s for s in result['steps'] if s['name']=='Маршрут API-шлюза')
    assert step['status']==('ok' if mismatch=='match' else 'error')
    assert 'local-test-secret' not in json.dumps(result) and 'outdated-secret' not in json.dumps(result)
    assert config.read_bytes()==before
