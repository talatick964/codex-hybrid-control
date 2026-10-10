"""Codex model descriptors, distinct from an OpenAI /models selector list."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
from functools import lru_cache


@lru_cache(maxsize=1)
def base_instructions():
    # Native Codex CLI 0.160.0 bundled instructions, not an invented prompt.
    return (Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'assets'/'codex-base-instructions.txt').read_text(encoding='utf-8')


def descriptor(slug,priority=99):
    # Required metadata accepted by installed Codex CLI 0.160.0. Provider
    # capability flags are conservative; availability is tested separately.
    return {'slug':slug,'display_name':slug,'description':'API provider selector; verify availability with diagnostics.',
        'base_instructions':base_instructions(),
        'default_reasoning_level':'low','supported_reasoning_levels':[
            {'effort':level,'description':level} for level in ('low','medium','high')],
        'shell_type':'unified_exec','visibility':'list','supported_in_api':True,'priority':priority,
        'additional_speed_tiers':[],'service_tiers':[],'availability_nux':None,'upgrade':None,
        'model_messages':None,'include_skills_usage_instructions':True,'include_plugin_usage_instructions':True,
        'include_apps_usage_instructions':True,'supports_reasoning_summary_parameter':False,
        'default_reasoning_summary':'none','support_verbosity':False,'default_verbosity':None,
        'apply_patch_tool_type':None,'web_search_tool_type':'text',
        'truncation_policy':{'mode':'bytes','limit':10000},'supports_image_detail_original':False,
        'context_window':None,'max_context_window':None,'effective_context_window_percent':95,
        'experimental_supported_tools':[],'input_modalities':['text','image'],'supports_search_tool':False,
        'use_responses_lite':False,'tool_mode':None,'multi_agent_version':None}


def catalog(models,source='Codex Hybrid Control'):
    return {'generated_by':source,'note':'Selectors do not prove provider capabilities or availability.',
            'models':[descriptor(model,index) for index,model in enumerate(dict.fromkeys(models))]}


def normalize(data,extract_ids):
    if not isinstance(data,dict) or not isinstance(data.get('models'),list) or not data['models']:
        raise ValueError('Каталог моделей пуст или имеет неверный формат')
    result=copy.deepcopy(data);rows=[]
    for index,row in enumerate(result['models']):
        if not isinstance(row,dict):raise ValueError('Некорректная запись каталога моделей')
        slug=row.get('slug') or row.get('id') or row.get('model')
        if not isinstance(slug,str) or not slug.strip():raise ValueError('В записи модели нет slug/id')
        defaults=descriptor(slug,index);defaults.update(row);defaults['slug']=slug
        rows.append(defaults)
    result['models']=rows
    return result


def validate(data):
    if not isinstance(data,dict) or not isinstance(data.get('models'),list) or not data['models']:
        raise ValueError('Каталог Codex должен содержать непустой массив models')
    for row in data['models']:
        required={'slug','display_name','supported_reasoning_levels','shell_type','visibility','supported_in_api',
                  'priority','default_reasoning_summary','support_verbosity','truncation_policy'}
        if not isinstance(row,dict) or any(key not in row for key in required):
            raise ValueError('Каталог содержит только идентификаторы или неполные метаданные. Выполните «Проверить и исправить всё».')
        if not isinstance(row['slug'],str) or not row['slug'].strip():raise ValueError('Неверный slug модели')
        messages=row.get('model_messages') or {}
        if not row.get('base_instructions') and not messages.get('instructions_template'):
            raise ValueError('В каталоге отсутствуют инструкции модели Codex; выполните общий ремонт')
    return data


def check_with_codex(core,path):
    # Offline parser check; no model inference, auth, user configuration or MCP.
    with tempfile.TemporaryDirectory(prefix='hybrid-catalog-check-') as temporary:
        env=dict(os.environ,CODEX_HOME=temporary,USERPROFILE=temporary,HOME=temporary)
        (Path(temporary)/'config.toml').write_text('model_catalog_json = '+core._toml_string(str(path.resolve()))+'\n',encoding='utf-8')
        result=core.run_bounded_process([core.codex_command(),'debug','models','--bundled'],timeout=8,env=env,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:
            raise RuntimeError('Codex CLI отклонил каталог: '+(result.stderr or '')[-800:])
    return True
