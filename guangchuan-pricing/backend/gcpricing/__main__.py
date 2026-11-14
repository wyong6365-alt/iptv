"""启动服务：python -m gcpricing。桌面版监听本机，云端通过 GC_HOST、GC_PORT、GC_DB_URL 配置。"""
import os

import uvicorn

from .api import create_app

if __name__ == "__main__":
    uvicorn.run(create_app(), host=os.environ.get("GC_HOST", "127.0.0.1"), port=int(os.environ.get("GC_PORT", "8765")))
