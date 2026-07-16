#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nv_p54.py —— P54 围肖信号模型（旧版信号 + 农历年适配）
目前尚未做优化,等待后续集成后考虑是否需要优化
============================================================
信号来源：54 条固化正向围肖信号（旧版 predict_54.py 原版）。
核心逻辑：
  1. 根据当期特肖，触发该生肖对应的若干条信号。
  2. 每条信号：取指定位置的号码或生肖 → 偏移 → 中心生肖 → 窗口围肖。
  3. 等权投票：窗口内的每个生肖各得 1 票。
  4. 冷号优先：同票数时，遗漏值大的排在前面。
  5. 取前 9 为九肖、前 6 为六肖、前 3 为三肖。

在集成中的角色：
  提供正向围肖的独立观点，与 M1（外部锚点规律）和 R96（规则库反向杀肖）互补。

依赖：
  - v2_shx_suishu（农历年生肖转换）
  - shuju_loader（数据加载）

用法：
  from nv_p54 import predict_p54, SIGNALS
  nine, six, three = predict_p54(records)
============================================================
"""

import os, sys
from collections import Counter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MARK6_DIR = os.path.join(BASE_DIR, "mark6")
if MARK6_DIR not in sys.path:
    sys.path.insert(0, MARK6_DIR)

from v2_shx_suishu import SHENGXIAO, get_lunar_year, get_shengxiao_by_suima
from shuju_loader import load_all_data

ZODIAC = SHENGXIAO
POS_NAMES = ["平一", "平二", "平三", "平四", "平五", "平六", "特码"]

# ===================== 54 条固化围肖信号 =====================
# 格式：{ 当期特肖: [ (位置, 类型, 偏移, 窗口半径), ... ] }
# 类型："号码" 表示从该位置的号码偏移后映射为中心生肖，
#       "生肖" 表示从该位置的生肖在生肖环上偏移得到中心生肖。
SIGNALS = {
    "马": [("平一", "号码", 8, 3), ("平三", "号码", 3, 3),
           ("平四", "生肖", -1, 1), ("平五", "号码", 10, 2),
           ("特码", "生肖", 6, 4)],
    "羊": [("平一", "号码", 2, 3), ("平三", "号码", 9, 4),
           ("平五", "号码", 3, 4)],
    "猴": [("平三", "号码", 8, 2), ("平四", "号码", 0, 2),
           ("平五", "生肖", 3, 4), ("平六", "号码", 10, 3)],
    "鸡": [("平二", "生肖", -5, 1), ("平三", "生肖", 2, 2),
           ("平四", "生肖", 6, 4), ("特码", "生肖", -5, 3)],
    "狗": [("平三", "号码", 2, 4), ("平四", "号码", 8, 2),
           ("平六", "号码", 2, 2), ("特码", "号码", 2, 4)],
    "猪": [("平一", "生肖", -5, 4), ("平二", "号码", 11, 2),
           ("平三", "号码", 1, 3), ("平四", "号码", 2, 3),
           ("平五", "号码", 3, 4)],
    "鼠": [("平一", "号码", 0, 1), ("平二", "生肖", 4, 4),
           ("平三", "生肖", 3, 1), ("平四", "号码", 3, 0)],
    "牛": [("平一", "号码", 5, 3), ("平二", "号码", 9, 4),
           ("平三", "号码", 2, 1), ("平四", "生肖", 1, 2),
           ("平五", "生肖", 5, 4), ("平六", "生肖", -4, 2)],
    "虎": [("平一", "号码", 3, 1), ("平三", "号码", 7, 3),
           ("平四", "号码", 10, 3), ("平六", "号码", 7, 4),
           ("特码", "号码", 8, 4)],
    "兔": [("平二", "号码", 6, 1), ("平三", "生肖", 2, 3),
           ("平五", "号码", 0, 1), ("特码", "生肖", 6, 4)],
    "龙": [("平一", "生肖", 3, 1), ("平二", "号码", 5, 3),
           ("平三", "号码", 10, 4), ("平四", "生肖", 2, 0),
           ("平五", "号码", 10, 2), ("特码", "生肖", 4, 1)],
    "蛇": [("平一", "号码", 10, 3), ("平四", "生肖", -5, 2),
           ("平五", "号码", 6, 4), ("特码", "号码", 3, 2)],
}


def offset_num(num, off):
    """号码偏移（1~49 循环）"""
    return (num - 1 + off) % 49 + 1


def get_window(center_sx, r):
    """以 center_sx 为中心，半径 r 的生肖窗口"""
    idx = ZODIAC.index(center_sx)
    return [ZODIAC[(idx + i) % 12] for i in range(-r, r + 1)]


def extract_records_lunar(data):
    """提取标准记录，使用农历年转换生肖"""
    records = []
    for item in data:
        try:
            qs = str(item.get("expect", ""))
            oc = str(item.get("openCode", ""))
            ot = item.get("openTime", "")
            if not qs or not oc:
                continue
            parts = oc.strip().split(",")
            if len(parts) != 7:
                continue
            nums = [int(p.strip()) for p in parts]
            lunar_year = get_lunar_year(ot)
            if lunar_year is None:
                continue
            records.append({
                "qishu": qs,
                "lunar_year": lunar_year,
                "te_num": nums[6],
                "te_sx": get_shengxiao_by_suima(nums[6], lunar_year),
                "ping_nums": nums[:6],
                "ping_sx": [get_shengxiao_by_suima(n, lunar_year) for n in nums[:6]],
            })
        except:
            continue
    records.sort(key=lambda x: int(x["qishu"]))
    return records


def predict_p54(records):
    """
    P54 围肖信号投票预测。
    输入：
        records: 历史记录列表（至少2条）
    输出：
        (nine, six, three) 三个列表
    """
    if len(records) < 2:
        return [], [], []

    latest_idx = len(records)
    curr = records[latest_idx - 1]
    cur_sx = curr["te_sx"]
    year = curr["lunar_year"]

    # 当期特肖没有对应信号时，返回空列表
    if cur_sx not in SIGNALS:
        return [], [], []

    sigs = SIGNALS[cur_sx]

    # 1. 计算遗漏值
    missing = {}
    for s in ZODIAC:
        streak = 0
        for i in range(latest_idx - 1, -1, -1):
            if records[i]["te_sx"] != s:
                streak += 1
            else:
                break
        missing[s] = streak

    # 2. 等权投票
    vc = Counter()
    for pos, stype, off, r in sigs:
        pos_idx = POS_NAMES.index(pos)
        num = curr["te_num"] if pos == "特码" else curr["ping_nums"][pos_idx]
        sx = curr["te_sx"] if pos == "特码" else curr["ping_sx"][pos_idx]

        if stype == "号码":
            # 号码偏移 → 中心生肖
            c = get_shengxiao_by_suima(offset_num(num, off), year)
        else:
            # 生肖偏移 → 中心生肖
            sx_idx = ZODIAC.index(sx)
            c = ZODIAC[(sx_idx + off) % 12]

        # 窗口内的所有生肖得票
        w = get_window(c, r)
        for s in w:
            vc[s] += 1

    # 3. 按票数降序，同票按遗漏值降序（冷号优先）
    ranked = sorted(vc.items(), key=lambda x: (-x[1], -missing.get(x[0], 0)))
    nine = [s for s, _ in ranked[:9]]
    six = [s for s, _ in ranked[:6]]
    three = [s for s, _ in ranked[:3]]

    return nine, six, three


# ===================== 自检 =====================
if __name__ == "__main__":
    print("P54 模型自检（旧版信号 + 农历年适配）")
    print("=" * 40)
    data = load_all_data(auto_update=False)
    records = extract_records_lunar(data)
    if len(records) >= 2:
        nine, six, three = predict_p54(records)
        latest = records[-1]
        print(f"基于期号: {latest['qishu']}")
        print(f"上期特肖: {latest['te_sx']}")
        print(f"九肖预测: {', '.join(nine)}")
        print(f"六肖预测: {', '.join(six)}")
        print(f"三肖预测: {', '.join(three)}")
    else:
        print("数据不足，无法预测。")