# -*- coding: utf-8 -*-
"""
虹语织 分层桌宠渲染器 (从 demo/pet_demo.py v3 移植)
====================================================
由 默认.psd 拆分图层驱动: 呼吸/马尾/呆毛/发片摆动 + 视线跟随 + 镜像翻转
+ 随机眨眼 + 说话嘴巴脉冲。main.py 在"默认"状态下用它替代静态 默认.png。

素材: resources/assets/layered/*.png + manifest.json (EXE 内为 assets/layered/)

供 main.py 调用的接口:
    LayeredPetRenderer(pet_size, layers_dir)     构造(按 pet_size 自动缩放)
    r.set_facing("left"/"right")                 镜像翻转(水平物理弹簧状态同步镜像, 屏幕方向连续)
    r.update_pointer(dx, dy, dt)                 鼠标相对眼部中心的偏移(px)
    r.set_talking(True/False)                    说话嘴巴动画
    r.set_working(True/False)                    任务执行时呆毛旋转(独立于聊天窗口)
    r.force_blink()                              强制眨一次眼
    r.kick(ax, ay)                               屏幕坐标冲量(自动乘 facing 转标准坐标)
    r.set_pet_velocity(vx, vy)                   屏幕坐标移动速度(px/s, 自动乘 facing)
    r.tick(now, extra_dy=0.0) -> PIL RGBA Image  渲染一帧(正方形, 边长=pet_size)

坐标系约定: 渲染先在"标准坐标(朝右)"合成, 最后按 facing 整帧镜像; 因此所有
屏幕坐标输入(冲量/速度)的水平分量都要乘 facing 转入标准坐标系, 翻转时存量
弹簧状态也要镜像重表达 —— 否则镜像后马尾飘动方向会与运动方向相反。
"""
import json
import math
import os
import sys
import random
import time

from PIL import Image

# ======================================================================
# ■■■■■  可调参数区 —— 动画手感(与 demo/pet_demo.py 保持一致) ■■■■■■■■
# ======================================================================

# ---------- 视线 / 头部跟随鼠标 ----------
GAZE_X, GAZE_Y = 3.0, 2.0    # 眼球最大偏移(px): 水平/垂直都收敛, 更含蓄
HEAD_FACTOR   = 0.30         # 头部跟随系数(降低, 头部移动更小)
EYE_EXTRA     = 0.55         # 眼球额外视线倍数(降低)
GAZE_RANGE    = 320.0        # 鼠标多远达到最大偏移(调大=更迟钝)
GAZE_SMOOTH   = 6.0          # 视线平滑速度
EYE_MIN_Y_PSD = 12.0         # 眼睛总下移量上限(含头部跟随, PSD px)
GAZE_Y_DOWN_DAMP = 0.45      # 朝下视线衰减(0~1)
GAZE_X_DAMP   = 0.60         # 水平视线衰减: 头/眼水平移动明显减小

# ---------- 摆动幅度(度) ----------
TAIL_SWAY    = 4.5           # 双马尾主摆幅
TAIL_SWAY2   = 1.5           # 双马尾高频小摆
AHOGE_SWAY   = 7.0           # 呆毛主摆幅
AHOGE_SWAY2  = 2.5           # 呆毛高频小摆
HAIR_SWAY    = 1.8           # 左右发片主摆幅
HAIR_SWAY2   = 0.8           # 发片高频小摆
HAIR_FOLLOW  = 0.12          # 发片跟随头部位移的甩动(度/px)

# ---------- 摆动速度 ----------
SPEED_TAIL  = 1.3
SPEED_AHOGE = 2.1
WORKING_SPIN_PERIOD = 1.5    # 执行任务时呆毛每圈秒数
SPEED_HAIR  = 1.0
SPEED_FLOAT = 1.1

# ---------- 浮动/连接 ----------
FLOAT_AMP   = 2.5            # 呼吸浮动幅度(px)
TAIL_FACTOR = 0.35           # 马尾跟随头部位移比例
HEAD_DROP   = 10.0           # 头部整体下沉(px, PSD坐标): 消除抬头时头与身体的空隙

# ---------- 移动物理(走动/漫游/拖动时的马尾) ----------
TAIL_DRAG_LAG    = 0.022     # 水平速度 -> 马尾滞后目标位移(px / (px/s))
TAIL_DRAG_LAG_Y  = 0.010     # 垂直速度 -> 滞后位移(px / (px/s))
TAIL_DRAG_MAX    = 26.0      # 滞后位移上限(px): 快速拖动甩尾不至于过度
TAIL_DRAG_SPRING = 25.0      # 滞后弹簧刚度(1/s^2)
TAIL_DRAG_DAMP   = 6.0       # 滞后阻尼(1/s), 欠阻尼有小回弹
TAIL_DRAG_DEG    = 0.90      # 滞后px -> 附加摆角(deg/px): 发根为轴心, 发尾大弧飘动
MOVE_ON_V        = 60.0      # 速度超过此值(px/s)判定"移动中" -> 正弦摆动让位物理
MOVE_OFF_V       = 30.0      # 速度低于此值(px/s)判定"静止" -> 恢复自然摆动(滞回带)

# ---------- 冲量弹簧(按真实时间归一, 与帧率无关) ----------
IMP_SPRING_K = 270.0         # 刚度(1/s^2)
IMP_DAMP     = 4.8           # 阻尼(1/s)
IMP_VSCALE   = 30.0          # kick 输入(px/帧@30fps 基准) -> px/s

# ---------- 眨眼 / 说话 ----------
BLINK_MIN, BLINK_MAX = 2.0, 6.0
BLINK_DURATION       = 0.30
TALK_AMP   = 0.55
TALK_SPEED = 11.0

# ---------- 关节 pivot (PSD 原始像素坐标) ----------
PIVOTS = {
    # 轴心 = 发根顶部(图层顶缘中心): 摆动时发尾划大弧, 发根几乎不动
    "tail_r": (2400, 1120),   # 右马尾发根(图层 bbox 2134,1087 顶部中心)
    "tail_l": (533, 1225),    # 左马尾发根(图层 bbox 243,1190 顶部中心)
    "ahoge":  (1556, 715),    # 呆毛发根
    "hair_r": (2215, 1040),   # 右发片发根
    "hair_l": (912, 1020),    # 左发片发根
    "eye_r":  (1977, 2095),   # 右眼中心
    "eye_l":  (1243, 2102),   # 左眼中心
}

# ======================================================================
# 以下为实现代码
# ======================================================================

K_TAIL_R = "右双马尾/颜色"
K_TAIL_L = "左双马尾/颜色"
K_AHOGE  = "呆毛/呆毛颜色"
K_PIN    = "发卡/颜色"
K_TURB_R = "右涡轮/颜色"
K_TURB_L = "左涡轮/颜色"
K_HAIRBASE = "头发底/图层 17"
K_BODY   = "身体（未拆分）/图层 7 副本 2"
K_FACE_S = "脸/皮肤颜色"
K_FACE_EL = "脸/右双眼皮"
K_FACE_ER = "脸/左双眼皮"
K_BROW_R = "眉毛/右眉毛"
K_BROW_L = "眉毛/左眉毛"
K_EYE_R  = "眼睛/右眼"
K_LID_R  = "眼睛/右眼皮"
K_EYE_L  = "眼睛/左眼"
K_LID_L  = "眼睛/左眼皮"
K_MOUTH  = "嘴巴/图层 2 副本 5"
K_HAIR_TOP = "上发片/图层 25"
K_HAIR_R = "右发片/图层 16"
K_HAIR_M = "中间发片/图层 15"
K_HAIR_L = "左发片/图层 14"

FACE_COMP = [K_FACE_S, K_FACE_EL, K_FACE_ER]
EYE_LAYERS = ((K_EYE_R, K_LID_R, K_BROW_R), (K_EYE_L, K_LID_L, K_BROW_L))

PSD_W, PSD_H = 2835, 3685    # 默认.psd 画布尺寸


def paste_over(canvas, sprite, x, y):
    x, y = int(x), int(y)
    w, h = sprite.size
    cx1, cy1 = max(0, x), max(0, y)
    cx2, cy2 = min(canvas.width, x + w), min(canvas.height, y + h)
    if cx2 <= cx1 or cy2 <= cy1:
        return
    region = canvas.crop((cx1, cy1, cx2, cy2))
    part = sprite.crop((cx1 - x, cy1 - y, cx2 - x, cy2 - y))
    canvas.paste(Image.alpha_composite(region, part), (cx1, cy1))


def rotate_around(img, pivot_in_img, deg):
    px, py = int(round(pivot_in_img[0])), int(round(pivot_in_img[1]))
    w, h = img.size
    hw, hh = max(px, w - px), max(py, h - py)
    padded = Image.new("RGBA", (hw * 2, hh * 2), (0, 0, 0, 0))
    padded.paste(img, (hw - px, hh - py))
    return padded.rotate(deg, resample=Image.BILINEAR, expand=True)


def squash_center(img, factor):
    h = img.size[1]
    nh = max(2, int(round(h * factor)))
    return img.resize((img.size[0], nh), Image.BILINEAR)


class LayeredPetRenderer:
    """分层渲染器; pet_size 为目标正方形边长(物理像素)。"""

    def __init__(self, pet_size, layers_dir=None):
        if layers_dir is None:
            # 资源解析顺序(全部基于绝对路径; 相对 CWD 在双击 exe 时不可靠):
            # 1) exe 旁的 assets/layered (绿色版/用户自备素材)
            # 2) PyInstaller 解包目录 _MEIPASS/assets/layered (打包内置)
            # 3) 源码运行: 项目 resources/assets/layered
            base = os.path.dirname(os.path.abspath(__file__))
            cands = []
            if getattr(sys, "frozen", False):
                cands.append(os.path.join(os.path.dirname(sys.executable), "assets", "layered"))
                cands.append(os.path.join(sys._MEIPASS, "assets", "layered"))
            cands.append(os.path.join(os.path.dirname(base), "resources", "assets", "layered"))
            layers_dir = next((c for c in cands
                               if os.path.exists(os.path.join(c, "manifest.json"))), cands[0])
        with open(os.path.join(layers_dir, "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)

        self.size = int(pet_size)
        self.scale = pet_size / float(PSD_H)      # 高度撑满
        self.W, self.H = self.size, self.size
        self.cache = {}

        # PSD 宽 2835 -> 渲染宽度 2835*scale < pet_size, 水平居中
        self.left_margin = (pet_size - PSD_W * self.scale) / 2.0
        # pivot 与图层坐标同基准: 都包含 left_margin (否则旋转部件整体偏移)
        self.piv = {k: (x * self.scale + self.left_margin, y * self.scale)
                    for k, (x, y) in PIVOTS.items()}

        self.img = {}
        self.pos = {}
        for m in manifest["layers"]:
            im = Image.open(os.path.join(layers_dir, m["file"])).convert("RGBA")
            tw = max(1, int(round(m["w"] * self.scale)))
            th = max(1, int(round(m["h"] * self.scale)))
            if im.size != (tw, th):
                im = im.resize((tw, th), Image.LANCZOS)
            self.img[m["key"]] = im
            self.pos[m["key"]] = (m["x"] * self.scale + self.left_margin,
                                  m["y"] * self.scale)

        self.face_comp, self.face_pos = self._compose(FACE_COMP)

        # ---- 头身缝合: 头部上移下限由身体图层顶缘决定(动态绑定) ----
        # body_top_y: 身体图层躯干范围内的最高不透明行(渲染坐标)
        # head_bottom_y: 脸图层最低不透明行
        # head_dy 下限 = body_top_y - head_bottom_y + 2px 重叠保险
        # (纯 PIL 实现, 不依赖 numpy — 打包版无需携带 numpy)
        def _first_opaque_row(img, x0, x1):
            alpha = img.getchannel("A")
            w = img.width
            x0 = max(0, x0); x1 = min(w, x1)
            for y in range(img.height):
                for x in range(x0, x1, 4):     # 隔4列采样, 足够定位顶缘
                    if alpha.getpixel((x, y)) > 10:
                        return y
            return None

        def _last_opaque_row(img):
            alpha = img.getchannel("A")
            for y in range(img.height - 1, -1, -1):
                for x in range(0, img.width, 4):
                    if alpha.getpixel((x, y)) > 10:
                        return y
            return None

        body = self.img[K_BODY]
        bx0 = int(922 * self.scale)
        bx1 = int(min(body.width, 2232 * self.scale))
        brow = _first_opaque_row(body, bx0, bx1)
        body_top_y = (self.pos[K_BODY][1] + brow) if brow is not None else 0.0
        frow = _last_opaque_row(self.img[K_FACE_S])
        head_bottom_y = (self.pos[K_FACE_S][1] + frow) if frow is not None else float(self.H)
        self._head_dy_min = (body_top_y - head_bottom_y) + 2.0

        self.next_blink = time.time() + random.uniform(1.5, 4.0)
        self.blink_start = None
        self.gaze = (0.0, 0.0)
        self.facing = 1
        self.anim_t = 0.0
        self.talking = False
        self.working = False
        self._working_phase = 0.0
        self.hair_on = True
        self._mood = None
        # 动作联动惯性
        self._imp_x = 0.0; self._imp_vx = 0.0
        self._imp_y = 0.0; self._imp_vy = 0.0
        # 移动物理: 走动/漫游/拖动时马尾的惯性滞后
        self._drag_x = 0.0; self._drag_vx = 0.0    # 水平滞后弹簧
        self._drag_y = 0.0; self._drag_vy = 0.0    # 垂直滞后弹簧
        self._pet_vel = (0.0, 0.0)                 # 宠物移动速度(px/s)
        self._last_t = None                        # 上一帧时间(Δt 计算)
        self._move_w = 0.0                         # 移动权重(0=静止正弦摆,1=纯物理)

    # ---------- 缓存 ----------
    def _cache_get(self, key, build):
        v = self.cache.get(key)
        if v is None:
            if len(self.cache) > 900:
                self.cache.clear()
            v = build()
            self.cache[key] = v
        return v

    def _compose(self, keys):
        x0 = min(self.pos[k][0] for k in keys)
        y0 = min(self.pos[k][1] for k in keys)
        x1 = max(self.pos[k][0] + self.img[k].width for k in keys)
        y1 = max(self.pos[k][1] + self.img[k].height for k in keys)
        cv = Image.new("RGBA", (int(x1 - x0), int(y1 - y0)), (0, 0, 0, 0))
        for k in keys:
            paste_over(cv, self.img[k], self.pos[k][0] - x0, self.pos[k][1] - y0)
        return cv, (x0, y0)

    # ---------- 姿态 ----------
    def pose(self, t):
        # 情绪调制: 睡觉=几乎静止, 想充电/思考中=放慢, 打扫=轻快, 递爱心=欢快
        if self._mood == "睡觉":
            spd_f = spd_t = spd_a = spd_h = 0.22
            amp_f = 0.35
        elif self._mood in ("想充电", "思考中"):
            spd_f = spd_t = spd_a = spd_h = 0.55
            amp_f = 0.7
        elif self._mood == "打扫卫生":
            spd_f, spd_t, spd_a, spd_h = SPEED_FLOAT * 1.4, SPEED_TAIL * 1.5, SPEED_AHOGE * 1.3, SPEED_HAIR * 1.4
            amp_f = 1.15
        elif self._mood == "递爱心":
            spd_f, spd_t, spd_a, spd_h = SPEED_FLOAT * 1.6, SPEED_TAIL * 1.6, SPEED_AHOGE * 1.8, SPEED_HAIR * 1.5
            amp_f = 1.3
        else:
            spd_f, spd_t, spd_a, spd_h = SPEED_FLOAT, SPEED_TAIL, SPEED_AHOGE, SPEED_HAIR
            amp_f = 1.0
        float_dy = FLOAT_AMP * amp_f * math.sin(t * spd_f)
        head_dy = float_dy + (FLOAT_AMP * 0.4) * amp_f * math.sin(t * spd_f + 0.6)
        tail_r = TAIL_SWAY * math.sin(t * spd_t + 0.5) + TAIL_SWAY2 * math.sin(t * spd_t * 2.08)
        tail_l = TAIL_SWAY * math.sin(t * spd_t + 2.2) + TAIL_SWAY2 * math.sin(t * spd_t * 2.08 + 1.1)
        ahoge = AHOGE_SWAY * math.sin(t * spd_a + 1.0) + AHOGE_SWAY2 * math.sin(t * spd_a * 2.05 + 0.3)
        if self.hair_on:
            hair_r = HAIR_SWAY * math.sin(t * spd_h + 0.8) + HAIR_SWAY2 * math.sin(t * spd_h * 2.3 + 0.4)
            hair_l = HAIR_SWAY * math.sin(t * spd_h + 2.5) + HAIR_SWAY2 * math.sin(t * spd_h * 2.3 + 1.6)
        else:
            hair_r = hair_l = 0.0
        # 想充电: 整体头下垂更多
        if self._mood == "想充电":
            head_dy += 4.0
        return dict(float_dy=float_dy, head_dy=head_dy,
                    tail_r=tail_r, tail_l=tail_l, ahoge=ahoge,
                    hair_r=hair_r, hair_l=hair_l)

    def update_pointer(self, dx, dy, dt):
        """鼠标相对"眼部中心"的偏移(px) + 帧间隔; 内部平滑出视线。"""
        target = (max(-1.0, min(1.0, dx / GAZE_RANGE)) * GAZE_X,
                  max(-1.0, min(1.0, dy / GAZE_RANGE)) * GAZE_Y)
        k = min(1.0, dt * GAZE_SMOOTH)
        self.gaze = (self.gaze[0] + (target[0] - self.gaze[0]) * k,
                     self.gaze[1] + (target[1] - self.gaze[1]) * k)

    def set_facing(self, facing):
        f = 1 if str(facing).lower() == "right" else -1
        if f == self.facing:
            return
        # 翻转时把水平物理状态镜像重表达: 弹簧状态存的是"标准坐标系(朝右)"的量,
        # 镜像渲染后屏幕效果不变 —— 马尾滞后/冲量方向连续, 翻转瞬间无跳变
        self._drag_x = -self._drag_x
        self._drag_vx = -self._drag_vx
        self._imp_x = -self._imp_x
        self._imp_vx = -self._imp_vx
        self.facing = f

    def set_talking(self, on):
        self.talking = bool(on)

    def set_mood(self, mood):
        """情绪驱动分层立绘:
        None/"默认"=活泼 | 睡觉=闭眼静止 | 想充电=低垂慢速 | 思考中=慢速凝视
        打扫卫生=轻快勤勉 | 递爱心=欢快弹跳 | 生气/脸红/嫌弃/疑惑=默认+说话表达"""
        m = mood if mood in ("睡觉", "想充电", "思考中", "打扫卫生", "递爱心") else None
        if m == self._mood:
            return
        self._mood = m
        if m == "睡觉":
            self.blink_start = None
            self.next_blink = float("inf")
        else:
            self.next_blink = time.time() + random.uniform(1.0, 3.0)
            self.blink_start = None
        if m == "递爱心":
            self.kick(ay=4.0)   # 开心小跳
        elif m == "打扫卫生":
            self.kick(ax=5.0)  # 干劲甩头

    # ---------- 物理动作联动 (main.py 的 bounce/shake 冲量传入) ----------
    def kick(self, ax=0.0, ay=0.0):
        """外力冲量: ax/ay 为屏幕坐标系的速度增量(px/帧@30fps基准) -> 头发部件惯性摆动。
        水平分量乘 facing 转为标准坐标(朝右) —— 翻转镜像渲染后屏幕方向才正确。"""
        self._imp_vx += ax * self.facing * IMP_VSCALE
        self._imp_vy += ay * IMP_VSCALE

    def set_pet_velocity(self, vx, vy):
        """报告宠物本体移动速度(px/s, 屏幕坐标): 走动/漫游/拖动时调用, 驱动马尾惯性滞后。
        水平速度乘 facing 转为标准坐标: 右移(屏幕vx>0)时发尾永远朝身体后方飘。"""
        self._pet_vel = (float(vx) * self.facing, float(vy))

    def _impulse_step(self, dt):
        """惯性摆动弹簧, 按真实 Δt 步进(帧率无关): 返回 (dx_shift, extra_sway_deg)。"""
        # 半隐式欧拉 + 子步进: 低帧率时把大 dt 切成 <=1/60 的小步, 积分精度一致
        n = max(1, int(math.ceil(dt / (1.0 / 60.0))))
        h = dt / n
        for _ in range(n):
            self._imp_vx += (-IMP_SPRING_K * self._imp_x - IMP_DAMP * self._imp_vx) * h
            self._imp_vy += (-IMP_SPRING_K * self._imp_y - IMP_DAMP * self._imp_vy) * h
            self._imp_x += self._imp_vx * h
            self._imp_y += self._imp_vy * h
        if abs(self._imp_x) < 0.02 and abs(self._imp_vx) < 0.5:
            self._imp_x = self._imp_vx = 0.0
        if abs(self._imp_y) < 0.02 and abs(self._imp_vy) < 0.5:
            self._imp_y = self._imp_vy = 0.0
        # 水平惯性 -> 头发附加摆角; 垂直惯性 -> 整体附加位移
        return self._imp_x, math.degrees(math.atan2(self._imp_x, 14.0))

    def _drag_step(self, dt):
        """移动滞后弹簧: 宠物位移时马尾根部"跟不上"产生的滞后角/位移。
        目标位移 = -速度 × 系数(速度越快滞后越大), 弹簧追踪, 欠阻尼带甩尾回弹。"""
        vx, vy = self._pet_vel
        tx = max(-TAIL_DRAG_MAX, min(TAIL_DRAG_MAX, -vx * TAIL_DRAG_LAG))
        ty = max(-TAIL_DRAG_MAX, min(TAIL_DRAG_MAX, -vy * TAIL_DRAG_LAG_Y))
        n = max(1, int(math.ceil(dt / (1.0 / 60.0))))
        h = dt / n
        for _ in range(n):
            self._drag_vx += ((tx - self._drag_x) * TAIL_DRAG_SPRING - self._drag_vx * TAIL_DRAG_DAMP) * h
            self._drag_vy += ((ty - self._drag_y) * TAIL_DRAG_SPRING - self._drag_vy * TAIL_DRAG_DAMP) * h
            self._drag_x += self._drag_vx * h
            self._drag_y += self._drag_vy * h
        # 移动状态权重: 速度>MOVE_ON 时马尾正弦摆动完全让位给物理;
        # 平滑过渡(静止→0, 移动→1), 停止后 ~0.4s 恢复自然摆动
        speed = math.hypot(vx, vy)
        w = 1.0 if speed > MOVE_ON_V else (0.0 if speed < MOVE_OFF_V else self._move_w)
        self._move_w += (w - self._move_w) * min(1.0, dt * 6.0)
        return self._move_w

    def force_blink(self):
        self.blink_start = time.time()
        self.next_blink = time.time() + random.uniform(BLINK_MIN, BLINK_MAX)

    def set_working(self, working):
        working = bool(working)
        if working != self.working:
            self._working_phase = 0.0
        self.working = working

    def _blink_amount(self, now):
        if self.blink_start is None:
            if now >= self.next_blink:
                self.blink_start = now
            return 0.0
        t = (now - self.blink_start) / BLINK_DURATION
        if t >= 1.0:
            self.blink_start = None
            self.next_blink = now + random.uniform(BLINK_MIN, BLINK_MAX)
            return 0.0
        return math.sin(math.pi * min(t, 1.0)) ** 1.2

    def draw_rot(self, canvas, key, pivot_name, deg, dx, dy):
        apx, apy = self.piv[pivot_name]
        img = self.img[key]
        q = round(deg * 2) / 2
        rot = self._cache_get((key, q), lambda: rotate_around(img, (apx - self.pos[key][0], apy - self.pos[key][1]), q))
        paste_over(canvas, rot, apx - rot.width / 2 + dx, apy - rot.height / 2 + dy)

    def _draw_eyes(self, canvas, blink, head_dx, head_dy, ex, ey):
        """Lower intact lids over the irises; brows follow without scaling."""
        blink = max(0.0, min(1.0, blink))
        for eye_key, lid_key, brow_key in EYE_LAYERS:
            eye = self.img[eye_key]
            covered = min(eye.height, int(round(eye.height * blink)))
            top = int(round(covered * 0.72))
            bottom = eye.height - (covered - top)
            if covered < eye.height:
                visible = self._cache_get((eye_key, "covered", covered),
                    lambda: eye.crop((0, top, eye.width, bottom)))
                paste_over(canvas, visible, self.pos[eye_key][0] + head_dx + ex,
                           self.pos[eye_key][1] + head_dy + ey + top)
            paste_over(canvas, self.img[lid_key], self.pos[lid_key][0] + head_dx + ex,
                       self.pos[lid_key][1] + head_dy + ey + top)
            paste_over(canvas, self.img[brow_key], self.pos[brow_key][0] + head_dx,
                       self.pos[brow_key][1] + head_dy + top * 0.12)

    # ---------- 整帧 ----------
    def tick(self, now=None, extra_dy=0.0):
        if now is None:
            now = time.time()
        # 真实 Δt: idle 摆动/物理弹簧全部按墙钟推进, 与渲染帧率无关
        if self._last_t is None:
            dt = 1.0 / 30.0
        else:
            dt = max(1e-4, min(0.2, now - self._last_t))
        self._last_t = now
        self.anim_t += dt
        if self.working:
            self._working_phase = (self._working_phase + dt / WORKING_SPIN_PERIOD) % 1.0
        p = self.pose(self.anim_t)
        blink = self._blink_amount(now)
        facing = self.facing
        if self._mood == "睡觉":
            blink = 1.0                      # 睡觉全程闭眼
            gx, gy = 0.0, 0.0                # 视线固定
        elif self._mood == "想充电":
            gx, gy = self.gaze[0] * facing * 0.3, 0.5 + self.gaze[1] * 0.3
        else:
            # 朝下视线衰减: gy>0(看下方)时乘阻尼, 避免眼睛贴近脸下缘
            gy_raw = self.gaze[1]
            if gy_raw > 0:
                gy = gy_raw * GAZE_Y_DOWN_DAMP
            else:
                gy = gy_raw
            gx = self.gaze[0] * facing

        # 眼睛总下移(头部跟随+额外视线)硬限制: 防止朝下看时贴到脸下缘
        gy_cap_total = (EYE_MIN_Y_PSD * self.scale) / max(HEAD_FACTOR + EYE_EXTRA, 0.001)
        gy = min(gy, gy_cap_total)

        head_dx = gx * HEAD_FACTOR
        # 头部下沉: HEAD_DROP 消除基准空隙; 上移下限由"身体顶缘"动态绑定:
        # 头底缘(脸+头发底最低行)任何姿态下都不高于身体图层顶缘 -> 永不分离
        head_dy = p["head_dy"] + gy * HEAD_FACTOR + HEAD_DROP * self.scale
        head_dy = max(head_dy, self._head_dy_min + HEAD_DROP * self.scale)

        # 动作联动惯性 + 移动滞后: 均按真实 Δt 步进
        imp_dx, imp_deg = self._impulse_step(dt)
        move_w = self._drag_step(dt)
        # 马尾滞后附加角/位移: 发尾朝运动反方向飘(右移->发尾向左后), 停下后回弹
        # PIL 正角=发尾向右: 右移(drag_x<0)需负角 -> drag_deg 与 drag_x 同号
        drag_deg = self._drag_x * TAIL_DRAG_DEG
        drag_dx = self._drag_x * 0.55
        drag_dy = self._drag_y * 0.40

        canvas = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))

        # 1. 双马尾(后层): 移动时正弦摆动淡出(只留物理), 静止时自然摆动+冲量
        sway_factor = 1.0 - move_w
        tail_deg = imp_deg * 1.6 + drag_deg
        tail_dx = head_dx * TAIL_FACTOR + imp_dx * 0.6 + drag_dx
        tail_dy = p["float_dy"] + extra_dy + drag_dy
        self.draw_rot(canvas, K_TAIL_R, "tail_r", p["tail_r"] * sway_factor + tail_deg,
                      tail_dx, tail_dy)
        self.draw_rot(canvas, K_TAIL_L, "tail_l", p["tail_l"] * sway_factor + tail_deg,
                      tail_dx, tail_dy)
        # 2. 呆毛(头顶): 弹簧幅度最大
        if not self.working:
            self.draw_rot(canvas, K_AHOGE, "ahoge", p["ahoge"] + imp_deg * 2.2, head_dx + imp_dx * 0.4, head_dy)
        # 冲量附加的垂直位移作用于头部组
        head_dy = head_dy + self._imp_y
        # 3. 发卡(帽子)/猫耳涡轮/头发底: 刚性跟随头部
        for key in (K_PIN, K_TURB_R, K_TURB_L, K_HAIRBASE):
            paste_over(canvas, self.img[key], self.pos[key][0] + head_dx, self.pos[key][1] + head_dy)
        # 4. 身体(只随呼吸)
        paste_over(canvas, self.img[K_BODY], self.pos[K_BODY][0], self.pos[K_BODY][1] + p["float_dy"] + extra_dy)
        # 5. 脸部合成
        paste_over(canvas, self.face_comp, self.face_pos[0] + head_dx, self.face_pos[1] + head_dy)
        # 6. 眼皮下移遮住眼球，眉毛轻微跟随，不压扁任何线条。
        ex, ey = gx * EYE_EXTRA, gy * EYE_EXTRA
        self._draw_eyes(canvas, blink, head_dx, head_dy, ex, ey)
        # 7. 嘴巴
        mox = self.pos[K_MOUTH][0] + head_dx
        moy = self.pos[K_MOUTH][1] + head_dy
        if self.talking:
            factor = 1.0 + TALK_AMP * abs(math.sin(now * TALK_SPEED))
            q = round(factor * 12) / 12
            mimg = self._cache_get((K_MOUTH, "tk", q), lambda: squash_center(self.img[K_MOUTH], q))
            paste_over(canvas, mimg, mox, moy)
        else:
            paste_over(canvas, self.img[K_MOUTH], mox, moy)
        # 8. 前发四片(保持 z 序)
        paste_over(canvas, self.img[K_HAIR_TOP],
                   self.pos[K_HAIR_TOP][0] + head_dx, self.pos[K_HAIR_TOP][1] + head_dy)
        self.draw_rot(canvas, K_HAIR_R, "hair_r",
                      p["hair_r"] + head_dx * HAIR_FOLLOW, head_dx, head_dy)
        paste_over(canvas, self.img[K_HAIR_M],
                   self.pos[K_HAIR_M][0] + head_dx, self.pos[K_HAIR_M][1] + head_dy)
        self.draw_rot(canvas, K_HAIR_L, "hair_l",
                      p["hair_l"] + head_dx * HAIR_FOLLOW, head_dx, head_dy)

        if self.working:
            # Draw in front while spinning so the head cannot hide half a turn.
            # Quantized angles bound the rotation cache across long-running tasks.
            spin = round(-360.0 * self._working_phase / 2.0) * 2.0
            self.draw_rot(canvas, K_AHOGE, "ahoge", spin, head_dx, head_dy)

        if facing == -1:
            canvas = canvas.transpose(Image.FLIP_LEFT_RIGHT)
        return canvas


def composite_flatten(frame, magic=(1, 1, 1)):
    """RGBA 帧 -> 带 chroma-key 底色的 RGB 图(供 ImageTk 直接显示)。"""
    bg = Image.new("RGB", frame.size, magic)
    bg.paste(frame, (0, 0), frame)
    return bg
