"""Keep local Codex bridges out of HTTP proxies without changing remote routing."""
import os

LOOPBACK_HOSTS=('127.0.0.1','localhost','::1')


def read_user_bypass():
    if os.name!='nt':return ''
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Environment') as key:
            value,_=winreg.QueryValueEx(key,'NO_PROXY')
            return value if isinstance(value,str) else ''
    except FileNotFoundError:return ''


def write_user_bypass(value):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,'Environment') as key:
        try:_,kind=winreg.QueryValueEx(key,'NO_PROXY')
        except FileNotFoundError:kind=winreg.REG_SZ
        if kind not in {winreg.REG_SZ,winreg.REG_EXPAND_SZ}:kind=winreg.REG_SZ
        winreg.SetValueEx(key,'NO_PROXY',0,kind,value)


def merge_bypass(*values):
    entries=[];seen=set()
    for value in (*values,','.join(LOOPBACK_HOSTS)):
        for entry in value.split(','):
            entry=entry.strip()
            if entry and entry.casefold() not in seen:
                entries.append(entry);seen.add(entry.casefold())
    return ','.join(entries)


def child_environment(source=None):
    result=dict(os.environ if source is None else source)
    bypass=[result.pop(key) for key in list(result) if key.casefold()=='no_proxy']
    value=merge_bypass(*bypass,read_user_bypass())
    result['NO_PROXY']=value
    result['no_proxy']=value
    return result


def repair_loopback_proxy(core):
    previous=read_user_bypass()
    env=child_environment()
    value=env['NO_PROXY']
    if os.name=='nt' and previous!=value:write_user_bypass(value)
    os.environ['NO_PROXY']=value
    os.environ['no_proxy']=value
    if os.name=='nt' and previous!=value:core._broadcast_environment_change()
    return 'Локальные шлюзы исключены из прокси. Остальные исключения и внешний прокси сохранены. Полностью перезапустите Codex.'
