"""Draw four Zhihu diagrams. Run: uv run --with pillow python 知乎文章-zhihu/_draw.py"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "images"
OUT.mkdir(parents=True, exist_ok=True)

BG = (244, 246, 250)
NAVY = (15, 23, 42)
NAVY2 = (30, 58, 138)
MUTED = (100, 116, 139)
WHITE = (255, 255, 255)
LAV = (237, 233, 254)
LAV_B = (91, 33, 182)
BLUE = (219, 234, 254)
BLUE_B = (29, 78, 216)
GREEN = (220, 252, 231)
GREEN_B = (21, 128, 61)
RED = (254, 226, 226)
RED_B = (185, 28, 28)
AMBER = (254, 243, 199)
AMBER_B = (180, 83, 9)
TEAL = (204, 251, 241)
TEAL_B = (15, 118, 110)
ORANGE = (255, 237, 213)
ORANGE_B = (194, 65, 12)

FONT = r"C:\Windows\Fonts\msyh.ttc"
FONTB = r"C:\Windows\Fonts\msyhbd.ttc"


def fnt(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONTB if bold else FONT, size)


def new(w: int, h: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGB", (w, h), BG)
    return im, ImageDraw.Draw(im)


def tw(d: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> float:
    return d.textlength(text, font=font)


def centered(d: ImageDraw.ImageDraw, x: float, y: float, text: str,
             font: ImageFont.FreeTypeFont, fill=NAVY) -> None:
    d.text((x - tw(d, text, font) / 2, y), text, font=font, fill=fill)


def rbox(d: ImageDraw.ImageDraw, xy, fill, outline, r=18, w=3) -> None:
    d.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=w)


def chip(d: ImageDraw.ImageDraw, xy, text, font) -> None:
    d.rounded_rectangle(xy, radius=10, fill=WHITE, outline=LAV_B, width=2)
    x1, y1, x2, y2 = xy
    centered(d, (x1 + x2) / 2, y1 + 8, text, font, LAV_B)


def arrow(d: ImageDraw.ImageDraw, x1, y1, x2, y2, fill=NAVY2, width=4) -> None:
    d.line((x1, y1, x2, y2), fill=fill, width=width)
    # simple head
    if abs(x2 - x1) >= abs(y2 - y1):
        s = 1 if x2 > x1 else -1
        d.polygon([(x2, y2), (x2 - 14 * s, y2 - 8), (x2 - 14 * s, y2 + 8)], fill=fill)
    else:
        s = 1 if y2 > y1 else -1
        d.polygon([(x2, y2), (x2 - 8, y2 - 14 * s), (x2 + 8, y2 - 14 * s)], fill=fill)


def title(d, w, main: str, sub: str) -> None:
    centered(d, w / 2, 28, main, fnt(36, True), NAVY)
    centered(d, w / 2, 80, sub, fnt(20), MUTED)


def draw_01() -> None:
    w, h = 1400, 900
    im, d = new(w, h)
    title(d, w, "控制面集中，数据面点对点", "池子只管协调，产出仍走 agent 之间")

    # orchestrator
    rbox(d, (80, 160, 360, 280), ORANGE, ORANGE_B)
    centered(d, 220, 188, "编排器", fnt(26, True), ORANGE_B)
    centered(d, 220, 230, "唯一推进时间的人", fnt(18), MUTED)

    arrow(d, 220, 280, 220, 340)

    # pool
    rbox(d, (80, 350, 1320, 560), LAV, LAV_B, r=22)
    centered(d, 700, 368, "POOL 控制面", fnt(28, True), LAV_B)
    centered(d, 700, 408, "不搬运工作内容", fnt(18), MUTED)
    chips = ["注册表", "会话", "活动日志", "批判线程", "满意度账本"]
    cw = 200
    gap = 24
    total = 5 * cw + 4 * gap
    x0 = 700 - total / 2
    for i, t in enumerate(chips):
        x = x0 + i * (cw + gap)
        chip(d, (x, 460, x + cw, 520), t, fnt(18, True))

    # down arrows from pool to agents
    for x in (250, 700, 1150):
        arrow(d, x, 560, x, 630)

    agents = [
        (80, 640, 420, 820, "writer", "起草"),
        (490, 640, 910, 820, "critic", "挑刺"),
        (980, 640, 1320, 820, "lead", "拍板"),
    ]
    for x1, y1, x2, y2, a, b in agents:
        rbox(d, (x1, y1, x2, y2), BLUE, BLUE_B)
        centered(d, (x1 + x2) / 2, y1 + 40, a, fnt(26, True), BLUE_B)
        centered(d, (x1 + x2) / 2, y1 + 90, b, fnt(20), MUTED)

    # p2p arrows between agents
    arrow(d, 420, 730, 490, 730)
    arrow(d, 910, 730, 980, 730)
    centered(d, 700, 850, "横向 A2A = 数据面（点对点）    向上看池 = 控制面（协调）", fnt(18), MUTED)
    im.save(OUT / "01-architecture.png", "PNG")


def draw_02() -> None:
    w, h = 1400, 820
    im, d = new(w, h)
    title(d, w, "停机条件只有一句", "每一位都满意，且没有任何未关闭的批判")

    boxes = [
        (60, 180, 300, 360, GREEN, GREEN_B, "产出", "写完一件事"),
        (380, 180, 640, 360, RED, RED_B, "批判", "撤销对方的满意"),
        (720, 180, 980, 360, AMBER, AMBER_B, "亲手解决", "修好，或论证不成立"),
        (1060, 180, 1340, 360, GREEN, GREEN_B, "重新签字", "再声明满意"),
    ]
    for x1, y1, x2, y2, fill, outline, a, b in boxes:
        rbox(d, (x1, y1, x2, y2), fill, outline)
        centered(d, (x1 + x2) / 2, y1 + 48, a, fnt(26, True), outline)
        centered(d, (x1 + x2) / 2, y1 + 108, b, fnt(18), MUTED)
    for x in (300, 640, 980):
        arrow(d, x, 270, x + 80, 270)

    rbox(d, (420, 420, 980, 530), TEAL, TEAL_B)
    centered(d, 700, 448, "全体收敛  →  停", fnt(28, True), TEAL_B)

    centered(d, 700, 560, "保险丝三道。原地打转，判失败。失败也是一种停。", fnt(20), MUTED)
    fuses = ["轮次上限", "无进展检测", "批判次数上限"]
    for i, t in enumerate(fuses):
        x = 200 + i * 360
        rbox(d, (x, 610, x + 280, 720), WHITE, NAVY2, r=16, w=2)
        centered(d, x + 140, 648, t, fnt(22, True), NAVY2)
    im.save(OUT / "02-stop-condition.png", "PNG")


def draw_03() -> None:
    w, h = 1400, 900
    im, d = new(w, h)
    title(d, w, "贵在历史重读，不在智能", "串行提示词总量是会计恒等式，不是曲线拟合")

    # left serial
    rbox(d, (60, 150, 680, 820), WHITE, BLUE_B, r=22, w=2)
    centered(d, 370, 175, "串行", fnt(28, True), BLUE_B)
    centered(d, 370, 220, "第 i 个人重读前 i−1 个人的产出", fnt(18), MUTED)

    widths = [180, 260, 340, 420, 500]
    labels = ["agent 1", "agent 2", "agent 3", "…", "agent N"]
    for i, (ww, lab) in enumerate(zip(widths, labels)):
        y = 280 + i * 70
        x1 = 370 - ww / 2
        fill = (191, 219, 254) if i < 4 else (96, 165, 250)
        rbox(d, (x1, y, x1 + ww, y + 52), fill, BLUE_B, r=10, w=2)
        centered(d, 370, y + 12, lab, fnt(18, True), NAVY2)

    centered(d, 370, 660, "pΣ ≈ N · p0 + ê · N(N−1)/2", fnt(20, True), NAVY)
    centered(d, 370, 710, "hold-out 预测 N=30，误差 −0.16%", fnt(18), MUTED)
    centered(d, 370, 755, "α = 2.05    R² = 0.99994", fnt(18), MUTED)

    # right parallel
    rbox(d, (720, 150, 1340, 820), WHITE, TEAL_B, r=22, w=2)
    centered(d, 1030, 175, "并行", fnt(28, True), TEAL_B)
    centered(d, 1030, 220, "墙钟 = 最慢的那个人 + 一点开销", fnt(18), MUTED)

    for i, lab in enumerate(["a0", "a1", "a2", "…", "aN"]):
        x = 800 + i * 100
        rbox(d, (x, 300, x + 80, 420), TEAL, TEAL_B, r=12)
        centered(d, x + 40, 340, lab, fnt(18, True), TEAL_B)

    rbox(d, (800, 470, 1260, 560), AMBER, AMBER_B, r=14)
    centered(d, 1030, 500, "N=30：串行 1.87 秒  →  并行 0.17 秒", fnt(18, True), AMBER_B)

    rbox(d, (800, 590, 1260, 680), RED, RED_B, r=14)
    centered(d, 1030, 620, "并行买不到 token", fnt(22, True), RED_B)

    centered(d, 1030, 730, "修好的两轮并行 ≈ 1.88 倍串行", fnt(18, True), NAVY)
    centered(d, 1030, 770, "朝 2 收敛：协调轮再付一次串行账单", fnt(16), MUTED)
    im.save(OUT / "03-cost-law.png", "PNG")


def draw_04() -> None:
    w, h = 1400, 860
    im, d = new(w, h)
    title(d, w, "0.18× 不是缩放，是 bug", "已读指针拨到自己的 finished 行，产出全躺在指针前面")

    # left triangle
    rbox(d, (50, 140, 680, 800), WHITE, RED_B, r=22, w=2)
    centered(d, 365, 165, "修前：三角形", fnt(26, True), RED_B)
    centered(d, 365, 210, "最后一个 agent 看到 0 行", fnt(18), MUTED)

    # artifacts row
    d.rounded_rectangle((90, 260, 640, 310), radius=8, fill=(226, 232, 240), outline=MUTED, width=2)
    centered(d, 365, 272, "2KB 产出（全部在指针前面）", fnt(16), MUTED)

    # red pointer
    d.line((90, 340, 640, 340), fill=RED_B, width=4)
    centered(d, 365, 350, "已读指针  ←  拨到自己的 finished", fnt(16, True), RED_B)

    bars = [520, 400, 280, 160, 40]
    labs = ["a0  29 行", "a1", "a2", "…", "aN  0 行"]
    for i, (bw, lab) in enumerate(zip(bars, labs)):
        y = 410 + i * 62
        x1 = 90
        fill = RED if i == 4 else (254, 202, 202)
        rbox(d, (x1, y, x1 + max(bw, 48), y + 44), fill, RED_B, r=8, w=2)
        d.text((x1 + 12, y + 8), lab, font=fnt(16, True), fill=NAVY)

    # right rectangle
    rbox(d, (720, 140, 1350, 800), WHITE, TEAL_B, r=22, w=2)
    centered(d, 1035, 165, "修后：矩形", fnt(26, True), TEAL_B)
    centered(d, 1035, 210, "第一个和最后一个看到的一样多", fnt(18), MUTED)

    d.rounded_rectangle((760, 260, 1310, 310), radius=8, fill=TEAL, outline=TEAL_B, width=2)
    centered(d, 1035, 272, "2KB 产出（全部在指针后面，被重喂）", fnt(16), TEAL_B)

    d.line((760, 340, 1310, 340), fill=TEAL_B, width=4)
    centered(d, 1035, 350, "已读指针  ←  恢复到本轮开始前", fnt(16, True), TEAL_B)

    for i, lab in enumerate(["a0", "a1", "a2", "…", "aN"]):
        y = 410 + i * 62
        rbox(d, (760, y, 1310, y + 44), TEAL, TEAL_B, r=8, w=2)
        d.text((780, y + 8), f"{lab}    全员看见全员", font=fnt(16, True), fill=NAVY)

    centered(d, 1035, 750, "整场成本 1.88 倍串行，和「约 2 倍」对上了", fnt(18, True), TEAL_B)
    im.save(OUT / "04-triangle-rectangle.png", "PNG")


if __name__ == "__main__":
    draw_01()
    draw_02()
    draw_03()
    draw_04()
    print("wrote", list(OUT.glob("*.png")))
