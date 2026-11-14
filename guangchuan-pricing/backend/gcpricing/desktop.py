"""桌面版启动器：在本机启动服务并用默认浏览器打开界面。

打包为 exe 后双击运行。出现一个小控制窗口，关闭它即退出程序。
参数 --smoke 用于构建后的自检：启动服务、请求界面和接口，然后退出。
"""
from __future__ import annotations

import socket
import sys
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from .db import data_dir

HOST = "127.0.0.1"
PREFERRED_PORT = 8765
TITLE = "广川AI智能组价平台"


def _redirect_output() -> None:
    """无控制台窗口的 exe 中 stdout、stderr 为空，改写到日志文件。"""
    if sys.stdout is None or sys.stderr is None:
        log = open(data_dir() / "desktop.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log


def _get(url: str, timeout: float = 2.0) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.read()
    except Exception:
        return None


def _is_our_app(port: int) -> bool:
    body = _get(f"http://{HOST}:{port}/api/auth/status", timeout=1.0)
    return body is not None and b"initialized" in body


def _free_port() -> int:
    for port in (PREFERRED_PORT, 0):
        with socket.socket() as s:
            try:
                s.bind((HOST, port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("没有可用端口")


def start_server() -> tuple[uvicorn.Server, int]:
    from .api import create_app

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(), host=HOST, port=port, log_config=None))
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.time() + 60
    while time.time() < deadline:
        if _is_our_app(port):
            return server, port
        time.sleep(0.2)
    raise RuntimeError("服务启动超时")


def smoke() -> int:
    server, port = start_server()
    page = _get(f"http://{HOST}:{port}/")
    ok = page is not None and b'id="root"' in page
    print(f"smoke: port={port} api=ok ui={'ok' if ok else 'MISSING'} data={data_dir()}")
    server.should_exit = True
    return 0 if ok else 1


def _control_window(url: str, on_quit) -> None:
    import tkinter as tk

    root = tk.Tk()
    root.title(TITLE)
    root.geometry("380x170")
    root.resizable(False, False)
    tk.Label(root, text=f"{TITLE} 正在运行", font=("Microsoft YaHei", 12, "bold")).pack(pady=(18, 4))
    tk.Label(root, text=f"界面地址：{url}\n数据保存在：{data_dir()}", justify="center").pack()
    row = tk.Frame(root)
    row.pack(pady=14)
    tk.Button(row, text="打开界面", width=12, command=lambda: webbrowser.open(url)).pack(side="left", padx=6)
    tk.Button(row, text="退出程序", width=12, command=root.destroy).pack(side="left", padx=6)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    on_quit()


def main() -> int:
    _redirect_output()
    if "--smoke" in sys.argv:
        return smoke()
    if _is_our_app(PREFERRED_PORT):  # 已经在运行，直接打开界面
        webbrowser.open(f"http://{HOST}:{PREFERRED_PORT}/")
        return 0
    server, port = start_server()
    url = f"http://{HOST}:{port}/"
    webbrowser.open(url)

    def stop():
        server.should_exit = True

    try:
        _control_window(url, stop)
    except Exception as exc:  # 没有图形环境时退回为前台运行
        print(f"{TITLE} 正在运行：{url}（控制窗口不可用：{exc}；按 Ctrl+C 退出）")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            stop()
    return 0
