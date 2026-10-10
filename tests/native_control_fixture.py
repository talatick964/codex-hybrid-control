"""Real standard Win32 controls for UI Automation integration checks."""
import ctypes
from ctypes import wintypes as w

u=ctypes.WinDLL('user32',use_last_error=True)
k=ctypes.WinDLL('kernel32',use_last_error=True)
callback_type=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,w.HWND,w.UINT,w.WPARAM,w.LPARAM)
u.DefWindowProcW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM];u.DefWindowProcW.restype=ctypes.c_ssize_t
u.CreateWindowExW.argtypes=[w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.HWND,w.HMENU,w.HINSTANCE,ctypes.c_void_p]
u.CreateWindowExW.restype=w.HWND
u.SetWindowTextW.argtypes=[w.HWND,w.LPCWSTR]
k.GetModuleHandleW.argtypes=[w.LPCWSTR];k.GetModuleHandleW.restype=w.HMODULE
label=None


@callback_type
def procedure(hwnd,msg,wp,lp):
    if msg==0x0111 and wp&0xffff==100:
        u.SetWindowTextW(label,'Verified result')
        return 0
    if msg==0x0002:
        u.PostQuitMessage(0)
        return 0
    return u.DefWindowProcW(hwnd,msg,wp,lp)


class WindowClass(ctypes.Structure):
    _fields_=[('style',w.UINT),('procedure',callback_type),('class_extra',ctypes.c_int),('window_extra',ctypes.c_int),
              ('instance',w.HINSTANCE),('icon',w.HICON),('cursor',w.HANDLE),('background',w.HBRUSH),
              ('menu',w.LPCWSTR),('name',w.LPCWSTR)]


instance=k.GetModuleHandleW(None)
window_class=WindowClass(0,procedure,0,0,instance,None,None,w.HBRUSH(6),None,'HybridUIAFixture')
u.RegisterClassW(ctypes.byref(window_class))
hwnd=u.CreateWindowExW(0,window_class.name,'Hybrid UIA test fixture',0x10CF0000,80,80,420,240,None,None,instance,None)
edit=u.CreateWindowExW(0,'EDIT','',0x50800080,20,25,300,24,hwnd,w.HMENU(101),instance,None)
button=u.CreateWindowExW(0,'BUTTON','Run test',0x50000000,20,70,140,30,hwnd,w.HMENU(100),instance,None)
label=u.CreateWindowExW(0,'STATIC','Waiting',0x50000000,20,120,300,30,hwnd,w.HMENU(102),instance,None)
u.ShowWindow(hwnd,5)
print(int(hwnd),flush=True)
message=w.MSG()
while u.GetMessageW(ctypes.byref(message),None,0,0)>0:
    u.TranslateMessage(ctypes.byref(message));u.DispatchMessageW(ctypes.byref(message))
