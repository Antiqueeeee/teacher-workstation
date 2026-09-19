"""系统类接口：访问地址与二维码。

老师要拿手机用，就得知道「输哪个网址」—— 让他手敲 `http://192.168.5.2:8723` 很容易敲错，
所以界面里给一个「手机访问」区块：**大字地址 + 二维码**（扫一下就打好了），
另外说明「手机要和这台电脑连同一个 WiFi」。

地址口径在 `services/access_info.py`（启动窗口用的是同一份）——
两处各算一遍迟早会出现「窗口里写 127.0.0.1、界面上写内网地址」这种自相矛盾。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.errors import INVALID_VALUE, ApiError
from app.services.access_info import access_info, all_lan_ips, is_local_ip, qr_svg

router = APIRouter(prefix="/system", tags=["系统"])


@router.get("/access")
def get_access(
    port: int | None = Query(default=None, description="一般不用传，按服务实际端口"),
    address: str | None = Query(default=None, description="用哪张网卡的地址（界面「换一个地址」用）"),
):
    """访问地址（本机 / 局域网 + 其它网卡候选）+ 二维码 SVG。

    二维码直接在响应里给 SVG 字符串：界面 `innerHTML` 塞进去就行，
    不必再发一个请求，也不必在前端实现二维码编码。

    `address` 只接受**本机自己**的地址（装了 VPN 的电脑会有多个候选，
    老师需要换一个试）；传别的地址会报错 —— 否则这就成了一个任意二维码生成器。
    """
    if address and not is_local_ip(address):
        raise ApiError(
            INVALID_VALUE,
            f"「{address}」不是这台电脑的地址（可选：{'、'.join(all_lan_ips())}）",
            detail={"field": "address", "value": address},
        )
    info = access_info(port, address)
    info["qrSvg"] = qr_svg(info["lan"])
    return {"ok": True, "data": info}
