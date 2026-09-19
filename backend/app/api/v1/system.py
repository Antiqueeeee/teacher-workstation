"""系统类接口：访问地址与二维码。

老师要拿手机用，就得知道「输哪个网址」—— 让他手敲 `http://192.168.5.2:8723` 很容易敲错，
所以界面里给一个「手机访问」区块：**大字地址 + 二维码**（扫一下就打好了），
另外说明「手机要和这台电脑连同一个 WiFi」。

地址口径在 `services/access_info.py`（启动窗口用的是同一份）——
两处各算一遍迟早会出现「窗口里写 127.0.0.1、界面上写内网地址」这种自相矛盾。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.access_info import access_info, qr_svg

router = APIRouter(prefix="/system", tags=["系统"])


@router.get("/access")
def get_access(port: int | None = Query(default=None, description="一般不用传，按服务实际端口")):
    """访问地址（本机 / 局域网）+ 二维码 SVG。

    二维码直接在响应里给 SVG 字符串：界面 `innerHTML` 塞进去就行，
    不必再发一个请求，也不必在前端实现二维码编码。
    """
    info = access_info(port)
    info["qrSvg"] = qr_svg(info["lan"])
    return {"ok": True, "data": info}
