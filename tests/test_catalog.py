import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest
import codex_hybrid_control as c
from hybrid_catalog import catalog,normalize,validate


def test_old_selectors_become_full_descriptors_without_metadata_ids():
    old={'models':[{'id':'selector','service_tiers':[{'id':'fast'}]}]}
    result=validate(normalize(old,c.extract_model_ids))
    assert result['models'][0]['slug']=='selector'
    assert result['models'][0]['base_instructions']
    assert c.extract_model_ids(result)==['selector']
    assert old['models'][0].get('slug') is None


def test_compatibility_rejects_selector_only_catalog():
    with pytest.raises(ValueError,match='метаданные'):validate({'models':[{'id':'model'}]})


def test_repair_preserves_and_upgrades_legacy_catalog(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'_home',lambda:tmp_path)
    monkeypatch.setattr(c,'get_user_api_key',lambda:None)
    monkeypatch.setattr(c,'user_api_key_present',lambda:False)
    c.bootstrap_codex_files();path=c.default_catalog_path()
    original=json.dumps({'models':[{'id':'legacy-model'}]})
    path.write_text(original,encoding='utf-8')
    c.repair_all(c.default_config_path())
    validate(json.loads(path.read_text(encoding='utf-8')))
    assert c.load_catalog_models(path)==['legacy-model']
    assert any(p.read_text(encoding='utf-8')==original for p in path.parent.glob('*.legacy-*.bak'))


def test_broken_alternate_provider_catalog_never_seeds_tokify_models(tmp_path,monkeypatch):
    monkeypatch.setattr(c,'_home',lambda:tmp_path)
    monkeypatch.setattr(c,'get_user_api_key',lambda:None)
    monkeypatch.setattr(c,'user_api_key_present',lambda:False)
    c.write_json_atomic(c.control_dir()/'active-connection.json',{'name':'Other','base_url':'https://example.com/v1',
                      'model':'custom','worker_models':{'opus':'worker'},'reasoning':'low'})
    c.bootstrap_codex_files();c.default_catalog_path().write_text('{bad',encoding='utf-8')
    c.repair_all(c.default_config_path())
    assert set(c.load_catalog_models(c.default_catalog_path()))=={'custom','worker'}


@pytest.mark.skipif(not shutil.which(c.codex_command()),reason='Codex CLI not installed')
def test_installed_codex_really_loads_generated_catalog(tmp_path):
    path=tmp_path/'models.json';path.write_text(json.dumps(catalog(['test-model'])),encoding='utf-8')
    (tmp_path/'config.toml').write_text('model = "test-model"\nmodel_catalog_json = '+c._toml_string(str(path))+'\n',encoding='utf-8')
    result=subprocess.run([c.codex_command(),'debug','prompt-input','CATALOG_PARSE_OK'],
        env=dict(os.environ,CODEX_HOME=str(tmp_path),USERPROFILE=str(tmp_path),HOME=str(tmp_path)),
        capture_output=True,text=True,encoding='utf-8',timeout=15)
    assert result.returncode==0,result.stderr
    assert 'CATALOG_PARSE_OK' in result.stdout
