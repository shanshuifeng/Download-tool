#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""netio.py —— 网络传输层（纯标准库）

把「怎么发请求」从「怎么下文件」里剥出来：UA、opener 缓存、代理（HTTP/SOCKS5）、
带超时与 UA 的 _request。上层只关心 URL，不关心走的是直连还是隧道。

分层约定：downloader 依赖 netio，netio 不得反向依赖 downloader。
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import struct
import threading
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

_DIRECT_WORDS = {"direct", "none", "off", "no"}
_OPENERS: dict[str, urllib.request.OpenerDirector] = {}
_OPENERS_LOCK = threading.Lock()


def _opener(proxy: str | None = None):  # @contract CORE-013
    """按代理设置取 opener（带缓存）。

    proxy=None      跟随 HTTP_PROXY / HTTPS_PROXY / NO_PROXY 环境变量
    proxy="direct"  强制直连（忽略环境变量）
    其他            视为代理地址，http 与 https 共用
    """
    key = "*" if proxy is None else proxy.strip()
    with _OPENERS_LOCK:
        got = _OPENERS.get(key)
    if got is not None:
        return got

    if key.lower().startswith(("socks5://", "socks5h://")):
        op = _socks_opener(key)
    elif key.lower() in _DIRECT_WORDS:
        ctx = ssl.create_default_context()
        op = urllib.request.build_opener(
            urllib.request.HTTPRedirectHandler(),
            urllib.request.HTTPSHandler(context=ctx),
            urllib.request.ProxyHandler({}))
    elif proxy is None:
        ctx = ssl.create_default_context()
        op = urllib.request.build_opener(
            urllib.request.HTTPRedirectHandler(),
            urllib.request.HTTPSHandler(context=ctx),
            urllib.request.ProxyHandler())  # 读环境变量
    else:
        ctx = ssl.create_default_context()
        op = urllib.request.build_opener(
            urllib.request.HTTPRedirectHandler(),
            urllib.request.HTTPSHandler(context=ctx),
            urllib.request.ProxyHandler({"http": key, "https": key}))
    with _OPENERS_LOCK:
        _OPENERS[key] = op
    return op


OPENER = _opener()  # 兼容旧引用；默认跟随环境变量


# ---------------- SOCKS5 ----------------

def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise OSError("SOCKS5 代理提前关闭了连接")
        buf += chunk
    return buf


def _socks5_addr(proxy_url: str):
    """解析 socks5://user:pass@host:port。"""
    raw = proxy_url if "://" in proxy_url else "socks5://" + proxy_url
    p = urllib.parse.urlparse(raw)
    return (p.hostname or "127.0.0.1", p.port or 1080,
            urllib.parse.unquote(p.username or ""),
            urllib.parse.unquote(p.password or ""))


def _socks5_connect(sock, host, port, user="", pwd=""):  # @contract CORE-017
    """在已建立的 TCP 连接上完成 SOCKS5 握手与 CONNECT。"""
    sock.sendall(b"\x05\x02\x00\x02" if user else b"\x05\x01\x00")
    ver, method = _recv_exact(sock, 2)
    if ver != 5:
        raise OSError("不是 SOCKS5 代理（版本号不符）")
    if method == 0x02:
        u, p = user.encode("utf-8"), pwd.encode("utf-8")
        sock.sendall(bytes([5, len(u)]) + u + bytes([len(p)]) + p)
        _, status = _recv_exact(sock, 2)
        if status != 0:
            raise OSError("SOCKS5 用户名或密码错误")
    elif method != 0x00:
        raise OSError("SOCKS5 代理不接受当前认证方式")

    try:
        ipaddress.ip_address(host)
        atyp, addr = b"\x01", socket.inet_aton(host)
    except ValueError:
        hb = host.encode("idna")
        atyp, addr = b"\x03", bytes([len(hb)]) + hb
    sock.sendall(b"\x05\x01\x00" + atyp + addr + struct.pack("!H", port))

    _, rep, _, rtype = _recv_exact(sock, 4)
    if rep != 0:
        raise OSError(f"SOCKS5 连接被拒绝（代码 {rep}）")
    if rtype == 0x01:
        _recv_exact(sock, 4 + 2)
    elif rtype == 0x03:
        _recv_exact(sock, _recv_exact(sock, 1)[0] + 2)
    elif rtype == 0x04:
        _recv_exact(sock, 16 + 2)


def _socks_opener(proxy_url: str):  # @contract CORE-017
    """构造走 SOCKS5 的 opener：连接时先握手，再把裸 socket 交给 http.client。"""
    phost, pport, puser, ppwd = _socks5_addr(proxy_url)

    class SocksHTTP(http.client.HTTPConnection):
        def connect(self):
            sock = socket.create_connection((phost, pport), self.timeout)
            sock.settimeout(self.timeout)
            _socks5_connect(sock, self.host, self.port, puser, ppwd)
            self.sock = sock

    class SocksHTTPS(http.client.HTTPSConnection):
        def connect(self):
            sock = socket.create_connection((phost, pport), self.timeout)
            sock.settimeout(self.timeout)
            _socks5_connect(sock, self.host, self.port, puser, ppwd)
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)

    class SocksHTTPHandler(urllib.request.HTTPHandler):
        def http_open(self, req):
            return self.do_open(SocksHTTP, req)

    class SocksHTTPSHandler(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(SocksHTTPS, req, context=self._context)

    ctx = ssl.create_default_context()
    return urllib.request.build_opener(SocksHTTPHandler(),
                                       SocksHTTPSHandler(context=ctx))


def _request(url: str, method="GET", headers=None, timeout=20, proxy=None):
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, method=method, headers=h)
    return _opener(proxy).open(req, timeout=timeout)
