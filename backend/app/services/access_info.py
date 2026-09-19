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


def all_lan_ips() -> list[str]:
    """本机所有可用的 IPv4（本机回环与链路本地地址除外），**探到的那个排第一**。

    为什么需要「所有」：装了 VPN、虚拟机或一堆网卡的电脑上，内核选出来的「默认出口」
    很可能是虚拟网卡 —— 那个地址手机根本连不上，而老师看不出哪儿错了
    （评审点过这个缺口）。所以把候选都列出来，让他换一个试。
    """
    primary = lan_ip()
    found: list[str] = []
    for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        ip = info[4][0]
        if ip == "127.0.0.1" or ip.startswith("169.254.") or ip in found:
            continue
        found.append(ip)
    if primary not in found and primary != "127.0.0.1":
        found.insert(0, primary)
    elif primary in found:
        found.remove(primary)
        found.insert(0, primary)
    return found or [primary]


def is_local_ip(ip: str) -> bool:
    """这个地址是不是本机的？（界面「换一个地址」用它做校验，别变成任意二维码生成器）"""
    return ip in all_lan_ips() or ip == "127.0.0.1"


def access_info(port: int | None = None, address: str | None = None) -> dict:
    """这台电脑上的访问地址：本机 + 局域网（可指定用哪张网卡的地址）。

    `lan` 是**手机要输的地址**（同一 WiFi 下可达）；`local` 只在本机有效。
    `alternatives` 是其它网卡上可能的地址（装了 VPN / 虚拟机时会有多个），
    老师按界面上的「换一个地址」挑选 —— 顺序按「探到的那个优先」。
    """
    resolved = port or PORT
    chosen = address or lan_ip()
    return {
        "port": resolved,
        "local": f"http://127.0.0.1:{resolved}/",
        "lan": f"http://{chosen}:{resolved}/",
        "alternatives": [
            {"ip": ip, "url": f"http://{ip}:{resolved}/"}
            for ip in all_lan_ips()
            if ip != chosen
        ],
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
