"""Bounded HTTP text reader with validated redirects and readable HTML extraction."""
from html.parser import HTMLParser
import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request


def validate_url(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname:
        raise ValueError('Нужен полный адрес HTTP или HTTPS.')
    if parsed.username or parsed.password:raise ValueError('Адреса с логином или паролем не поддерживаются.')
    host=parsed.hostname.rstrip('.').lower()
    if host=='localhost' or host.endswith(('.localhost','.local','.internal')):
        raise ValueError('Локальные и внутренние адреса запрещены.')
    port=parsed.port or (443 if parsed.scheme=='https' else 80)
    try:addresses=[ipaddress.ip_address(host)]
    except ValueError:
        addresses=[ipaddress.ip_address(row[4][0].split('%')[0]) for row in socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)]
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError('Локальные и внутренние адреса запрещены.')
    return url


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        validate_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


class ReadableHTML(HTMLParser):
    def __init__(self,url):
        super().__init__(convert_charrefs=True)
        self.url=url;self.parts=[];self.title=[];self.links=[];self.hidden=0;self.in_title=False
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','svg'):self.hidden+=1
        if tag=='title':self.in_title=True
        if tag in ('p','div','br','li','h1','h2','h3','section','article'):self.parts.append('\n')
        if tag=='a':
            href=dict(attrs).get('href','')
            if not href or href.startswith('#'):return
            link=urllib.parse.urljoin(self.url,href)
            if urllib.parse.urlsplit(link).scheme in ('http','https') and link not in self.links and len(self.links)<30:self.links.append(link)
    def handle_endtag(self,tag):
        if tag in ('script','style','svg'):self.hidden=max(0,self.hidden-1)
        if tag=='title':self.in_title=False
        if tag in ('p','div','li','h1','h2','h3','section','article'):self.parts.append('\n')
    def handle_data(self,data):
        if self.hidden:return
        if self.in_title:self.title.append(data)
        else:self.parts.append(data)


def fetch(url,timeout=15):
    url=str(url or '').strip()
    try:
        validate_url(url)
        timeout=max(1,min(float(timeout),30))
        request=urllib.request.Request(url,headers={'User-Agent':'CodexHybridBrowser/7.0','Accept':'text/html,application/json,text/plain'})
        opener=urllib.request.build_opener(SafeRedirect())
        with opener.open(request,timeout=timeout) as response:
            final_url=response.url
            validate_url(final_url)
            raw=response.read(2*1024*1024+1)
            if len(raw)>2*1024*1024:raise ValueError('Страница превышает лимит 2 МБ.')
            content_type=response.headers.get_content_type()
            if not (content_type.startswith('text/') or content_type in ('application/json','application/xhtml+xml')):
                raise ValueError('Этот формат не поддерживается текстовым браузером.')
            charset=response.headers.get_content_charset() or 'utf-8'
            try:text=raw.decode(charset,errors='replace')
            except LookupError:text=raw.decode('utf-8',errors='replace')
            status=response.status
        if content_type in ('text/html','application/xhtml+xml'):
            reader=ReadableHTML(final_url);reader.feed(text)
            body='\n'.join(' '.join(line.split()) for line in ''.join(reader.parts).splitlines() if line.strip())
            title=' '.join(''.join(reader.title).split())
            links=reader.links
        else:body=text;title='';links=[]
        return {'ok':True,'url':final_url,'status':status,'title':title[:200],'text':body[:32000],
                'chars':len(body),'links':links,'truncated':len(body)>32000}
    except urllib.error.HTTPError as error:
        return {'ok':False,'url':url,'error':f'HTTP {error.code}'}
    except (OSError,ValueError,urllib.error.URLError) as error:
        return {'ok':False,'url':url,'error':str(error)}
