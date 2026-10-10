"""Bounded Windows UI Automation in an isolated PowerShell process."""
import base64
import hashlib
import json
import os
import subprocess
import time
from hybrid_process import run_bounded


SCRIPT = r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName WindowsBase
$providers=[Reflection.Assembly]::Load('UIAutomationClientsideProviders, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35')
$desktop=[System.Windows.Automation.AutomationElement]::RootElement
[System.Windows.Automation.ClientSettings]::RegisterClientSideProviderAssembly($providers.GetName())
$data = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__REQUEST__')) | ConvertFrom-Json
$root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]([long]$data.hwnd))
if (!$root) { throw 'Окно недоступно для UI Automation' }
$pidValue=$root.Current.ProcessId
$started=(Get-Process -Id $pidValue).StartTime.ToUniversalTime().Ticks.ToString()
if ($data.pid -and (($pidValue -ne $data.pid) -or ($started -ne $data.started))) { throw 'Окно изменилось; получите новый список элементов' }
$walker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
$queue=[Collections.Generic.Queue[object]]::new()
$queue.Enqueue($root)
$rows=[Collections.Generic.List[object]]::new()
$count=0
$found=$null
while ($queue.Count -gt 0 -and $count -lt [int]$data.limit) {
 $element=$queue.Dequeue();$count++
 try {
  $current=$element.Current
  $rid=($element.GetRuntimeId() -join '.')
  if ($data.runtime_id -and $rid -eq $data.runtime_id) { $found=$element;break }
  if (!$data.runtime_id -and !$current.IsOffscreen) {
   $rect=$current.BoundingRectangle
   $rows.Add(@{runtime_id=$rid;name=$current.Name;automation_id=$current.AutomationId;type=$current.ControlType.ProgrammaticName;class_name=$current.ClassName;enabled=$current.IsEnabled;password=$current.IsPassword;bounds=@{x=$rect.X;y=$rect.Y;width=$rect.Width;height=$rect.Height};invoke=[bool]$element.GetCurrentPropertyValue([System.Windows.Automation.AutomationElement]::IsInvokePatternAvailableProperty);value=[bool]$element.GetCurrentPropertyValue([System.Windows.Automation.AutomationElement]::IsValuePatternAvailableProperty)})
  }
  $child=$walker.GetFirstChild($element)
  while ($child -and $queue.Count -lt [int]$data.limit) { $queue.Enqueue($child);$child=$walker.GetNextSibling($child) }
 } catch [System.Windows.Automation.ElementNotAvailableException] {}
}
if ($data.runtime_id) {
 if (!$found) { throw 'Элемент больше не доступен; получите новый список' }
 $current=$found.Current
 if ($current.Name -ne $data.name -or $current.ControlType.ProgrammaticName -ne $data.type -or $current.AutomationId -ne $data.automation_id) { throw 'Элемент изменился; получите новый список' }
 if (!$current.IsEnabled) { throw 'Элемент отключён' }
 if ($data.operation -eq 'invoke') {
  $pattern=$found.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
  $pattern.Invoke()
  @{ok=$true;dispatched=$true;verified=$false;hint='Проверьте ожидаемое состояние окна отдельным чтением или снимком'} | ConvertTo-Json -Compress
 } elseif ($data.operation -eq 'set_value') {
  if ($current.IsPassword) { throw 'Парольные поля требуют явного ручного ввода' }
  $pattern=$found.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
  if ($pattern.Current.IsReadOnly) { throw 'Поле доступно только для чтения' }
  $pattern.SetValue([string]$data.value)
  $matched=($pattern.Current.Value -ceq [string]$data.value)
  @{ok=$matched;dispatched=$true;verified=$matched;chars=([string]$data.value).Length} | ConvertTo-Json -Compress
 } else { throw 'Неподдерживаемая операция' }
} else {
 @{ok=$true;pid=$pidValue;started=$started;elements=@($rows.ToArray());truncated=($queue.Count -gt 0)} | ConvertTo-Json -Depth 8 -Compress
}
'''


def _request(data, timeout=12):
    if os.name != 'nt': raise RuntimeError('UI Automation доступен только в Windows')
    encoded = base64.b64encode(json.dumps(data, ensure_ascii=False).encode('utf-8')).decode('ascii')
    script = SCRIPT.replace('__REQUEST__', encoded)
    encoded_script = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    result = run_bounded(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded_script],
                         timeout=timeout, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        # PowerShell error output includes source lines; never return the request.
        raise RuntimeError('UI Automation не выполнил запрос: окно/элемент недоступен, '
                           'поле защищено или приложение не поддерживает нужный шаблон. Получите новый список или используйте мышь.')
    return json.loads(result.stdout.lstrip('\ufeff'))


class Accessibility:
    def __init__(self, core):
        self.core = core

    def inspect(self, hwnd, limit=180):
        policy = self.core.computer_policy()
        if not policy.get('enabled'): raise RuntimeError('Локальный мост отключён')
        if policy.get('control_mode') == 'mouse': raise RuntimeError('Включён режим только мыши и клавиатуры')
        limit = max(1,min(int(limit),400))
        data = _request({'hwnd':int(hwnd),'limit':limit})
        if not data.get('ok'): return data
        import uuid
        snapshot_id = uuid.uuid4().hex
        cache = {'created_at':time.time(),'hwnd':int(hwnd),'pid':data['pid'],
                 'started':data['started'],'elements':{}}
        for element in data['elements']:
            eid = hashlib.sha256((snapshot_id+element['runtime_id']).encode()).hexdigest()[:20]
            cache['elements'][eid] = element
            element['element_id'] = snapshot_id+':'+eid
        self.core.write_json_atomic(self.core.control_dir()/'uia'/f'{snapshot_id}.json',cache)
        folder = self.core.control_dir()/'uia'
        for old in folder.glob('*.json'):
            if time.time()-old.stat().st_mtime > 300:
                try: old.unlink()
                except OSError: pass
        return data

    def act(self, element_id, operation, value=None):
        self.core._require_input_policy()
        if self.core.computer_policy().get('control_mode') == 'mouse':
            raise RuntimeError('Включён режим только мыши и клавиатуры')
        import re
        if not re.fullmatch(r'[a-f0-9]{32}:[a-f0-9]{20}', str(element_id)):
            raise ValueError('Неверный element_id')
        snapshot_id, key = element_id.split(':')
        path = self.core.control_dir()/'uia'/f'{snapshot_id}.json'
        cache = self.core.read_json(path,{})
        element = cache.get('elements',{}).get(key)
        if not element or time.time()-cache.get('created_at',0)>90:
            raise RuntimeError('Список элементов устарел; получите его заново')
        if operation not in {'invoke','set_value'}: raise ValueError('Неподдерживаемая операция')
        if operation=='set_value' and (value is None or len(str(value))>12000):
            raise ValueError('Значение поля должно содержать не более 12000 символов')
        # Invalidate before dispatch: even a timeout can have changed the UI.
        path.unlink()
        return _request({'hwnd':cache['hwnd'],'pid':cache['pid'],'started':cache['started'],
                         'runtime_id':element['runtime_id'],'name':element['name'],
                         'automation_id':element['automation_id'],'type':element['type'],
                         'operation':operation,'value':value,'limit':1200})
