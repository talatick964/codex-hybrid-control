"""Keep local Codex bridges out of HTTP proxies without changing remote routing."""
import os

LOOPBACK_HOSTS=('127.0.0.1','localhost','::1')


def read_system_proxy_enabled():
    """Read only presence, never expose a Windows proxy URL or credentials."""
    if os.name!='nt':return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Internet Settings') as key:
            def value(name):
                try:return winreg.QueryValueEx(key,name)[0]
                except FileNotFoundError:return None
            return bool(value('ProxyEnable') or value('AutoConfigURL'))
    except FileNotFoundError:return False


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


def loopback_status(source=None):
    """Describe inherited routing without returning proxy URLs or credentials."""
    source=os.environ if source is None else source
    values=[value for key,value in source.items() if key.casefold()=='no_proxy']
    exclusions=[{entry.strip().casefold() for entry in value.split(',')} for value in values] or [set()]
    # Libraries disagree on casing precedence. Conflicting inherited values
    # must not be reported as healthy merely because one spelling is correct.
    missing=[host for host in LOOPBACK_HOSTS
             if any('*' not in entries and host not in entries for entries in exclusions)]
    saved={entry.strip().casefold() for entry in read_user_bypass().split(',')}
    saved_ok='*' in saved or set(LOOPBACK_HOSTS)<=saved
    system_proxy_present=read_system_proxy_enabled()
    proxy_present=system_proxy_present or any(value for key,value in source.items()
                      if key.casefold() in {'http_proxy','https_proxy','all_proxy','ag_ls_proxy'})
    return {'proxy_present':bool(proxy_present),'system_proxy_present':system_proxy_present,'missing_hosts':missing,
            'restart_required':bool(proxy_present and missing and saved_ok),
            'ok':not proxy_present or not missing}


def repair_loopback_proxy(core):
    previous=read_user_bypass()
    env=child_environment()
    value=env['NO_PROXY']
    if os.name=='nt' and previous!=value:write_user_bypass(value)
    os.environ['NO_PROXY']=value
    os.environ['no_proxy']=value
    if os.name=='nt' and previous!=value:core._broadcast_environment_change()
    return 'Локальные шлюзы исключены из прокси. Остальные исключения и внешний прокси сохранены. Полностью перезапустите Codex.'
