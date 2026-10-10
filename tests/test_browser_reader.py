from email.message import Message
import socket
import pytest
import hybrid_browser as browser


def test_local_addresses_rejected_without_fetch():
    for url in ['http://127.0.0.1','http://10.1.2.3','http://[::1]','http://localhost','file:///secret','http://169.254.169.254']:
        assert not browser.fetch(url)['ok']


def test_dns_private_and_redirect_target_rejected(monkeypatch):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('192.168.1.5',80))])
    assert not browser.fetch('https://example.com')['ok']
    with pytest.raises(ValueError):
        browser.SafeRedirect().redirect_request(None,None,302,'',{},'http://127.0.0.1/private')


def test_relative_links_entities_and_script_removal(monkeypatch):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])
    class Response:
        url='https://example.com/folder/index.html'
        status=200
        headers=Message()
        headers['Content-Type']='text/html; charset=made-up-charset'
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,n):return b'<title>A &amp; B</title><p>Hello &lt;world&gt;</p><script>secret script</script><a href="../next?q=1&amp;x=2">Next</a>'
    class Opener:
        def open(self,*a,**k):return Response()
    monkeypatch.setattr(browser.urllib.request,'build_opener',lambda *a:Opener())
    result=browser.fetch('https://example.com')
    assert result['ok'] and result['title']=='A & B'
    assert 'Hello <world>' in result['text'] and 'secret script' not in result['text']
    assert result['links']==['https://example.com/next?q=1&x=2']


def test_timeout_becomes_visible_error(monkeypatch):
    monkeypatch.setattr(browser,'validate_url',lambda url:url)
    class Opener:
        def open(self,*a,**k):raise TimeoutError('timed out')
    monkeypatch.setattr(browser.urllib.request,'build_opener',lambda *a:Opener())
    assert browser.fetch('https://example.com')['error']=='timed out'
