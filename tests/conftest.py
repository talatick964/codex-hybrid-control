import pytest


@pytest.fixture(autouse=True)
def no_background_daemons_in_unit_tests(monkeypatch, tmp_path):
    # Real gateway tests create and close their own in-process servers.
    # Config/GUI unit tests must not leave detached daemons behind.
    import hybrid_api_guard
    import codex_hybrid_control as core
    import os
    monkeypatch.setenv('NO_PROXY',os.environ.get('NO_PROXY',''))
    monkeypatch.setenv('no_proxy',os.environ.get('no_proxy',''))
    monkeypatch.setattr(core, '_home', lambda: tmp_path)
    monkeypatch.setattr(hybrid_api_guard, 'ensure_started', lambda core: None)
    import hybrid_proxy
    monkeypatch.setattr(hybrid_proxy,'read_user_bypass',lambda:'')
    monkeypatch.setattr(hybrid_proxy,'write_user_bypass',lambda value:None)
    monkeypatch.setattr(core,'_broadcast_environment_change',lambda:None)
