"""Bounded end-to-end check in an isolated Codex home; never changes user settings."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid
import ctypes
import sys
from PIL import Image, ImageDraw, ImageFont
import codex_hybrid_control as core
from hybrid_connections import active_connection
from hybrid_diagnostics import redact
from hybrid_process import kill_tree


def main():
    connection=active_connection(core);key=core.get_user_api_key()
    model=connection.get('model') or 'gpt-5.6-sol'
    outcome={'ok':False,'model':model,'scope':'Изолированный Codex CLI → API → настоящий MCP; чтение статуса и тестового изображения.'}
    if not key:
        outcome['reason']='API-ключ не настроен'
    else:
        with tempfile.TemporaryDirectory(prefix='hybrid-codex-e2e-') as temporary:
            home=Path(temporary);core._home=lambda:home
            core.write_json_atomic(core.control_dir()/'active-connection.json',connection)
            core.bootstrap_codex_files();core.apply_mode(core.default_config_path(),'api',model,'low')
            core.prepare_api_autonomy(core.default_config_path())
            core.save_computer_policy({'enabled':True,'allow_input':False,'allow_launch':False,'allow_screenshot':True})
            fixture=subprocess.Popen([sys.executable,str(Path(__file__).parent/'tests'/'native_control_fixture.py')],
                         stdout=subprocess.PIPE,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            hwnd=int(fixture.stdout.readline());window_code=str(int(uuid.uuid4().hex[:4],16)%9000+1000)
            label=ctypes.windll.user32.GetDlgItem(hwnd,102)
            ctypes.windll.user32.SetWindowTextW(ctypes.c_void_p(label),'Image check '+window_code)
            image=Image.new('RGB',(360,120),'white');draw=ImageDraw.Draw(image)
            draw.text((45,25),'4287',fill='black',font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',64))
            image_path=home/'test.png';image.save(image_path)
            project=home/'fixture';project.mkdir();nonce=uuid.uuid4().hex[:10]
            prompt=('Это ограниченная проверка подключения. Не используй shell, браузер, воркеров, запись файлов или ввод. '
                    'Вызови hybridComputer computer_status ровно один раз, затем computer_screenshot для hwnd='+str(hwnd)+'. '
                    'На снимке окна прочитай четыре цифры после Image check. Прочитай четыре цифры на прикреплённом изображении. '
                    'После реального результата инструмента ответь только JSON с полями nonce="'+nonce+'", '
                    'code (цифры прикреплённого изображения), window_code (цифры снимка MCP), bridge_seen (true если реальный инструмент ответил). Не придумывай результат.')
            env=dict(os.environ,USERPROFILE=str(home),HOME=str(home),CODEX_HOME=str(core.codex_dir()))
            env[core.API_ENV_KEY]=key
            command=[core.codex_command(),'exec','--ephemeral','--skip-git-repo-check','--json','--color','never',
                     '--sandbox','read-only','-c','approval_policy="never"','-c','web_search="disabled"',
                     '-c','mcp_servers.hybridComputer.tools.computer_status.approval_mode="approve"',
                     '-c','mcp_servers.hybridComputer.tools.computer_screenshot.approval_mode="approve"',
                     '-C',str(project),'-i',str(image_path),'--',prompt]
            started=time.monotonic()
            process=subprocess.Popen(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                      creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),text=True,encoding='utf-8',errors='replace')
            try:
                out,err=process.communicate(timeout=90)
                events=[]
                for line in out.splitlines():
                    try:events.append(json.loads(line))
                    except ValueError:pass
                items=[event.get('item',{}) for event in events]
                calls=[item for item in items if item.get('type')=='mcp_tool_call']
                seen=any(item.get('tool')=='computer_status' and item.get('status')=='completed' and not item.get('error') for item in calls)
                screenshot_seen=any(item.get('tool')=='computer_screenshot' and item.get('status')=='completed' and not item.get('error') for item in calls)
                messages=[item.get('text','') for item in items if item.get('type')=='agent_message']
                answer={}
                if messages:
                    try:answer=json.loads(messages[-1].strip().removeprefix('```json').removesuffix('```').strip())
                    except ValueError:pass
                outcome.update(ok=process.returncode==0 and seen and screenshot_seen and answer.get('nonce')==nonce and answer.get('code')=='4287' and answer.get('window_code')==window_code,
                    exit_code=process.returncode,mcp_status_confirmed=seen,image_confirmed=answer.get('code')=='4287',
                    mcp_image_confirmed=screenshot_seen and answer.get('window_code')==window_code,
                    event_types=sorted({e.get('type','') for e in events}),
                    tool_calls=[{'tool':i.get('tool'),'status':i.get('status'),'error':redact(i.get('error'),(key,))} for i in calls],
                    errors=[redact(str(e.get('message') or e.get('error') or ''),(key,))[:500] for e in events if e.get('type') in {'error','turn.failed'}])
                if not outcome['ok'] and not outcome['errors']:
                    outcome['reason']='Проверка не подтвердила все условия; '+redact(err,(key,))[-700:]
            except subprocess.TimeoutExpired:
                kill_tree(process);process.communicate(timeout=10)
                outcome['reason']='Codex/API не завершил проверку за 90 секунд; тестовое дерево процессов остановлено.'
            finally:
                ctypes.windll.user32.PostMessageW(hwnd,0x0010,0,0)
                try:fixture.wait(timeout=5)
                except subprocess.TimeoutExpired:fixture.kill();fixture.wait()
            outcome['elapsed_seconds']=round(time.monotonic()-started,2)
    path=Path(__file__).parent/'artifacts'/'final-codex-e2e.json'
    path.write_text(json.dumps(redact(outcome,(key,)),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(outcome,ensure_ascii=True),flush=True)


if __name__=='__main__':main()
