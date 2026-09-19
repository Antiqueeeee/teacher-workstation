"""访问地址：**「手机该访问哪个地址」只有这一处实现**。

启动窗口（`launcher.py`）、界面里的「手机访问」、以后的二维码，都从这里取地址 ——
这个地址算错一次就是老师拿着手机连不上（而且他看不出是哪儿错了）。

局域网地址的取法：往一个外网地址「连」一下 UDP，让内核告诉我们默认出口网卡是哪个 IP。
**不会真的发包、也不需要联网**（离线环境照样成立）。
"""

from __future__ import annotations

import socket

from app.config import PORT

# 探针地址：不会真的发包，只是让内核选路由
_PROBE = ("10.255.255.255", 1)


def lan_ip() -> str:
    """本机在局域网里的地址；取不到就退回 127.0.0.1（至少能本机用）。

    **socket 创建失败也要兜住**：完全没有网卡的机器上，`socket()` 自己就抛 OSError ——
    那时候启动器不该崩，退化成「只能本机访问」并说明清楚就够了。
    """
    probe = None
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(_PROBE)
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        if probe is not None:
            probe.close()


def access_info(port: int | None = None) -> dict:
    """这台电脑上的访问地址：本机与局域网各一个。

    `lan` 是**手机要输的地址**（同一 WiFi 下可达）；`local` 只在本机有效。
    """
    resolved = port or PORT
    return {
        "port": resolved,
        "local": f"http://127.0.0.1:{resolved}/",
        "lan": f"http://{lan_ip()}:{resolved}/",
    }


def qr_svg(text: str, scale: int = 4) -> str:
    """把地址渲染成二维码（内联 SVG）。

    用 segno（纯 Python、无依赖、MIT）—— **不能引 CDN 上的二维码脚本**：
    部署环境不联网，那种东西在老师的电脑上一定加载失败。
    """
    import segno  # 局部导入：地址解析与二维码是两件事，少了 segno 也要能给地址

    return segno.make(text, error="m").svg_inline(scale=scale, dark="#263b49", border=2)


def qr_terminal(text: str) -> str:
    """给启动窗口用的**终端二维码**（用块字符画出来，不需要浏览器）。

    终端编码不支持块字符时由调用方兜住（返回空串，让老师去界面里看）。
    """
    import io

    import segno

    buffer = io.StringIO()
    segno.make(text, error="m").terminal(out=buffer, compact=True)
    return buffer.getvalue()
