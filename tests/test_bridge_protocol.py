import json
import os
from pathlib import Path
import subprocess
import sys


def run_bridge(entry, messages, tmp_path):
    env = dict(os.environ, USERPROFILE=str(tmp_path), HOME=str(tmp_path), PYTHONIOENCODING='utf-8')
    run = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / entry)],
                         input='\n'.join(json.dumps(m) for m in messages)+'\n',
                         capture_output=True, text=True, encoding='utf-8', env=env, timeout=12)
    assert run.returncode == 0, run.stderr
    return [json.loads(line) for line in run.stdout.splitlines() if line.strip()]


def test_worker_protocol_initialization_and_empty_registry(tmp_path):
    result = run_bridge('worker_bridge_entry.py', [
        {'jsonrpc':'2.0','id':1,'method':'initialize'},
        {'jsonrpc':'2.0','method':'notifications/initialized'},
        {'jsonrpc':'2.0','id':2,'method':'tools/list'},
        {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'api_worker_list','arguments':{}}},
    ], tmp_path)
    assert [row['id'] for row in result] == [1,2,3]
    assert len(result[1]['result']['tools']) == 4
    assert not result[2]['result'].get('isError')


def test_computer_protocol_rejects_local_fetch_without_hanging(tmp_path):
    result = run_bridge('computer_bridge_entry.py', [
        {'jsonrpc':'2.0','id':1,'method':'initialize'},
        {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'browser_fetch','arguments':{'url':'http://127.0.0.1/'}}},
        {'jsonrpc':'2.0','id':3,'method':'ping'},
    ], tmp_path)
    assert [row['id'] for row in result] == [1,2,3]
    content = result[1]['result']['content']
    payload = json.loads(next(row['text'] for row in content if row['type']=='text'))
    assert not payload['ok']


def test_mcp_uses_utf8_even_with_legacy_windows_codepage(tmp_path):
    request={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'несуществующий','arguments':{}}}
    env=dict(os.environ,USERPROFILE=str(tmp_path),HOME=str(tmp_path),PYTHONIOENCODING='cp1251')
    entry=Path(__file__).resolve().parents[1]/'worker_bridge_entry.py'
    result=subprocess.run([sys.executable,str(entry)],input=(json.dumps(request,ensure_ascii=False)+'\n').encode('utf-8'),
                          capture_output=True,env=env,timeout=12)
    data=json.loads(result.stdout.decode('utf-8'))
    assert data['result']['isError']
    assert 'несуществующий' in data['result']['content'][0]['text']
