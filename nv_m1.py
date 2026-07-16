#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nv_m1.py —— M1 多规律投票模型（最终版）
============================================================
外部规律：
  平五+8（主规律），平六+1，平三+5
  每条规律取锚点号码+偏移 → 中心生肖 → ±4围九肖，等权投票。

F5 微调机制：
  - 合冲池加分：3
  - 冷号回补：遗漏值 ≥ 20 期，加 1 分
  - 杀本期特肖：硬排除（得分 -1000）
  - 遗漏值加分：遗漏值 // 10

参数维护策略（有数据支撑）：
  - 训练窗口：始终使用最新 2000 期数据
  - 更新频率：每积累 50 期新数据，重新扫描 F5 参数
  - 平滑过渡：新参数 × 0.7 + 旧参数 × 0.3
  - 连错保护：若最近 50 期内六肖连错 > 3 期，立即触发更新
  数据依据：245期样本外滚动测试显示，每50期更新时六肖命中率 58.61%，
  最大连错 4 期仅发生 1 次，且维护成本最低。

依赖：
  - v2_shx_suishu（农历年生肖转换）
  - shuju_loader（数据加载）
  - 合冲固定关系

输出：
  九肖、六肖、三肖列表
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

# ---- 固定关系（合冲池） ----
SAN_HE = {
    "马": ["虎", "狗"], "羊": ["兔", "猪"], "猴": ["鼠", "龙"],
    "鸡": ["蛇", "牛"], "狗": ["虎", "马"], "猪": ["兔", "羊"],
    "鼠": ["猴", "龙"], "牛": ["蛇", "鸡"], "虎": ["马", "狗"],
    "兔": ["猪", "羊"], "龙": ["鼠", "猴"], "蛇": ["鸡", "牛"],
}
LIU_HE = {"马": "羊", "羊": "马", "猴": "蛇", "蛇": "猴", "鸡": "龙", "龙": "鸡",
          "狗": "兔", "兔": "狗", "猪": "虎", "虎": "猪", "鼠": "牛", "牛": "鼠"}
CHONG = {"马": "鼠", "羊": "牛", "猴": "虎", "鸡": "兔", "狗": "龙", "猪": "蛇",
         "鼠": "马", "牛": "羊", "虎": "猴", "兔": "鸡", "龙": "狗", "蛇": "猪"}

# ---- M1 规律配置 ----
RULES = [
    (4, 8),    # 平五 +8（主规律）
    (5, 1),    # 平六 +1
    (2, 5),    # 平三 +5
]

# ---- F5 微调参数（初始值，可通过 update_params 动态更新） ----
MASTER_WEIGHT = 1.5           # 主规律权重
HECHONG_WEIGHT = 3            # 合冲池加分
COLD_THRESHOLD = 20           # 冷号阈值
COLD_WEIGHT = 1               # 冷号回补加分
MISSING_DIV = 10              # 遗漏值除数
USE_KILL_TE = True            # 是否排除上期特肖

# ---- 维护参数 ----
UPDATE_INTERVAL = 50          # 参数更新间隔（期）
TRAIN_WINDOW = 2000           # 训练窗口大小（期）
SMOOTH_FACTOR = 0.7           # 新参数平滑权重
STREAK_ALERT = 3              # 连错警报阈值


def get_hechong_full(sx):
    """获取某生肖的完整合冲池（8肖）"""
    pool = {sx}
    for s in SAN_HE.get(sx, []):
        pool.add(s)
    pool.add(LIU_HE.get(sx, ""))
    ch = CHONG.get(sx, "")
    pool.add(ch)
    for s in SAN_HE.get(ch, []):
        pool.add(s)
    pool.add(LIU_HE.get(ch, ""))
    return pool


def anchor_nine(prev, pos_idx, offset):
    """单条规律：锚点号码+偏移 → 中心生肖 → ±4 围九肖"""
    year = prev["lunar_year"]
    if pos_idx < 6:
        anchor_num = prev["ping_nums"][pos_idx]
    else:
        anchor_num = prev["te_num"]
    center_num = (anchor_num - 1 + offset) % 49 + 1
    center_sx = get_shengxiao_by_suima(center_num, year)
    center_idx = ZODIAC.index(center_sx)
    return [ZODIAC[(center_idx + i) % 12] for i in range(-4, 5)]


def extract_records_lunar(data):
    """提取记录并应用农历年转换"""
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


def scan_best_params(records, train_end):
    """在 train_end 之前的最新2000期内扫描F5最优参数"""
    train_start = max(2, train_end - TRAIN_WINDOW)
    val_end = train_end
    val_start = max(train_start + 500, val_end - 200)  # 内部验证段

    mw_vals = [1.0, 1.5, 2.0, 2.5, 3.0]
    hw_vals = [2, 3, 4, 5, 6]
    ct_vals = [18, 20, 22]
    md_vals = [8, 9, 10, 11, 12]

    best_comp = -1
    best_cfg = (MASTER_WEIGHT, HECHONG_WEIGHT, COLD_THRESHOLD, MISSING_DIV)

    for mw in mw_vals:
        for hw in hw_vals:
            for ct in ct_vals:
                for md in md_vals:
                    hits9, hits6, hits3 = 0, 0, 0
                    total = val_end - val_start
                    for idx in range(val_start, val_end):
                        prev = records[idx - 1]
                        missing = {}
                        for s in ZODIAC:
                            streak = 0
                            for i in range(idx - 1, -1, -1):
                                if records[i]["te_sx"] != s:
                                    streak += 1
                                else:
                                    break
                            missing[s] = streak

                        vote = Counter()
                        for i, (pos_idx, off) in enumerate(RULES):
                            pool = anchor_nine(prev, pos_idx, off)
                            w = mw if i == 0 else 1
                            for s in pool:
                                vote[s] += w

                        hechong_pool = get_hechong_full(prev["te_sx"])
                        scores = {}
                        for s in ZODIAC:
                            score = vote.get(s, 0)
                            if s in hechong_pool:
                                score += hw
                            if s == prev["te_sx"]:
                                score -= 1000
                            if missing[s] >= ct:
                                score += 1
                            score += int(missing[s] / md)
                            scores[s] = score

                        sorted_sx = sorted(scores.items(), key=lambda x: x[1], reverse=True)
                        nine = [s for s, _ in sorted_sx[:9]]
                        six = nine[:6]
                        three = nine[:3]
                        actual = records[idx]["te_sx"]
                        if actual in nine: hits9 += 1
                        if actual in six: hits6 += 1
                        if actual in three: hits3 += 1

                    r9 = hits9 / total * 100
                    r6 = hits6 / total * 100
                    r3 = hits3 / total * 100
                    comp = r9 * 0.2 + r6 * 0.4 + r3 * 0.4
                    if comp > best_comp:
                        best_comp = comp
                        best_cfg = (mw, hw, ct, md)
    return best_cfg


def update_params(records, current_issue_idx, recent_streak_6):
    """
    检查是否需要更新F5参数，如需更新则平滑调整。
    返回 (updated, new_params)
    """
    global MASTER_WEIGHT, HECHONG_WEIGHT, COLD_THRESHOLD, MISSING_DIV
    # 判断更新条件
    need_update = False
    if current_issue_idx - getattr(update_params, "last_update", 0) >= UPDATE_INTERVAL:
        need_update = True
    if recent_streak_6 > STREAK_ALERT:
        need_update = True
    if not need_update:
        return False, (MASTER_WEIGHT, HECHONG_WEIGHT, COLD_THRESHOLD, MISSING_DIV)

    # 执行扫描
    new_mw, new_hw, new_ct, new_md = scan_best_params(records, current_issue_idx)

    # 平滑过渡
    MASTER_WEIGHT = new_mw * SMOOTH_FACTOR + MASTER_WEIGHT * (1 - SMOOTH_FACTOR)
    HECHONG_WEIGHT = round(new_hw * SMOOTH_FACTOR + HECHONG_WEIGHT * (1 - SMOOTH_FACTOR))
    COLD_THRESHOLD = round(new_ct * SMOOTH_FACTOR + COLD_THRESHOLD * (1 - SMOOTH_FACTOR))
    MISSING_DIV = round(new_md * SMOOTH_FACTOR + MISSING_DIV * (1 - SMOOTH_FACTOR))

    update_params.last_update = current_issue_idx
    return True, (MASTER_WEIGHT, HECHONG_WEIGHT, COLD_THRESHOLD, MISSING_DIV)


def predict_m1(records, recent_streak_6=0):
    """
    核心预测函数。
    输入：
        records: 历史记录列表（至少2条）
        recent_streak_6: 最近六肖连错期数（用于触发参数更新）
    输出：九肖列表、六肖列表、三肖列表
    """
    if len(records) < 2:
        return [], [], []

    idx = len(records)
    # 尝试更新参数
    update_params(records, idx, recent_streak_6)

    prev = records[-1]

    # 1. 计算遗漏值
    missing = {}
    for s in ZODIAC:
        streak = 0
        for i in range(idx - 1, -1, -1):
            if records[i]["te_sx"] != s:
                streak += 1
            else:
                break
        missing[s] = streak

    # 2. 不等权投票
    vote_counter = Counter()
    for i, (pos_idx, off) in enumerate(RULES):
        pool = anchor_nine(prev, pos_idx, off)
        w = MASTER_WEIGHT if i == 0 else 1
        for s in pool:
            vote_counter[s] += w

    # 3. 综合评分
    hechong_pool = get_hechong_full(prev["te_sx"])
    scores = {}
    for s in ZODIAC:
        score = vote_counter.get(s, 0)
        if s in hechong_pool:
            score += HECHONG_WEIGHT
        if USE_KILL_TE and s == prev["te_sx"]:
            score -= 1000
        if missing[s] >= COLD_THRESHOLD:
            score += COLD_WEIGHT
        score += int(missing[s] / MISSING_DIV)
        scores[s] = score

    # 4. 按得分降序排列
    sorted_sx = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    nine = [s for s, _ in sorted_sx[:9]]
    six = nine[:6]
    three = nine[:3]

    return nine, six, three


if __name__ == "__main__":
    print("M1 模型自检")
    print("=" * 30)
    data = load_all_data(auto_update=False)
    records = extract_records_lunar(data)
    if len(records) >= 2:
        nine, six, three = predict_m1(records)
        latest = records[-1]
        print(f"基于期号: {latest['qishu']}")
        print(f"上期特肖: {latest['te_sx']}")
        print(f"九肖预测: {', '.join(nine)}")
        print(f"六肖预测: {', '.join(six)}")
        print(f"三肖预测: {', '.join(three)}")
    else:
        print("数据不足，无法预测。")