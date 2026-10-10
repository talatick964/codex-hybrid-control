"""Test-only MCP: count invocations in an isolated temporary directory."""
import json
from pathlib import Path
import sys

counter=Path(sys.argv[1])
for line in sys.stdin:
    request=json.loads(line)
    if 'id' not in request:
        continue
    method=request['method']
    result={}
    if method=='initialize':
        result={'protocolVersion':'2025-06-18','capabilities':{'tools':{}},'serverInfo':{'name':'counter','version':'1'}}
    elif method=='tools/list':
        result={'tools':[{'name':'observe','description':'Return a fixed test status (with an internal invocation log)',
                         'annotations':{'readOnlyHint':True,'destructiveHint':False,'openWorldHint':False},
                         'inputSchema':{'type':'object','properties':{}}}]}
    elif method=='tools/call':
        value=int(counter.read_text())+1 if counter.exists() else 1
        counter.write_text(str(value))
        result={'content':[{'type':'text','text':'unchanged' if '--fixed' in sys.argv else str(value)}]}
    print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
