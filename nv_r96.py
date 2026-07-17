#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nv_r96.py —— R96 反向杀肖评分模型（待优化版）
============================================================
定位：
  集成中的辅助投票方，提供与 M1/P54 不同方向的反向杀肖信号。
  当 M1 和 P54 同时偏向某个错误生肖时，R96 的金标惩罚可将该生肖拉低。

核心逻辑（基于 V5.1 简化版 model_r96，已移除负贡献组件）：
  评分 = 遗漏值分段加权 + 金标投票惩罚 + 冷却惩罚
         + 平五窗口加分 + 合冲池加分 + 特码金标杀肖扣分
         + 固定杀肖降权（扣分而非硬排除）

规则库消费：
  - 双锚点金标规则库（nv_双锚点规则库.json）：匹配位置对+生肖对投票
  - 三锚点超金标规则库（nv_三锚点规则库.json）：匹配位置三元组投票（权重×2）

已知局限：
  - 单独使用时六肖连错 5 期，无法满足 ≤3 的硬性约束
  - 样本外六肖命中率约 55%，仅略高于随机基线
  - 需在集成中与 M1/P54 配合使用，依赖投票互救降低组合连错

待优化方向（集成后根据实际表现决定）：
  - 规则库构建参数（min_samples, min_kill_rate）的重新扫描
  - 金标惩罚力度与遗漏值加权的平衡
  - 三锚点规则库的利用方式（当前权重×2 可能不是最优）

用法：
  from nv_r96 import predict_r96
  nine, six, three = predict_r96(records)
============================================================
"""

import json, os, sys
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MARK6_DIR = os.path.join(BASE_DIR, "mark6")
if MARK6_DIR not in sys.path:
    sys.path.insert(0, MARK6_DIR)

from v2_shx_suishu import SHENGXIAO, get_lunar_year, get_shengxiao_by_suima
from shuju_loader import load_all_data

ZODIAC = SHENGXIAO
POS_NAMES = ["平一", "平二", "平三", "平四", "平五", "平六", "特码"]
OFFSETS = list(range(-5, 7))

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

# ---- R96 评分参数（内部扫描最优，待集成后可能调整） ----
GOLD_SCALE = 1.5               # 金标惩罚系数
COOL_WINDOW = 3                # 冷却窗口（近N期出现过的特肖扣分）
COOL_PENS = [10, 5, 2]         # 冷却惩罚力度（1期前/2期前/3期前）
PING5_WEIGHT = 15              # 平五+8窗口加分
HECHONG_WEIGHT = 12            # 合冲池加分
TE_WEIGHT = 5                  # 特码金标杀肖扣分
FIXED_PENALTY = 20             # 固定杀肖降权力度（平二+3 + 本期特肖）
MISSING_THRESH = (8, 20)       # 遗漏值分段阈值
MISSING_WEIGHTS = (1.0, 2.0, 3.0)  # 遗漏值分段权重
GOLD_PENS = [3, 8, 15, 30]     # 金标投票惩罚阶梯
ANCHOR3_WEIGHT = 2             # 三锚点规则投票权重


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


def offset_num(num, off):
    """号码偏移（1~49循环）"""
    return (num - 1 + off) % 49 + 1


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


def load_rulebase(filename):
    """加载规则库文件，返回字典"""
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path):
        print(f"[R96] 警告：规则库文件不存在 {filename}")
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def predict_r96(records, rules_gold=None, rules_3anchor=None):
    """
    R96 反向杀肖评分预测。
    输入：
        records: 历史记录列表（至少2条）
        rules_gold: 双锚点规则库（可选，默认自动加载）
        rules_3anchor: 三锚点规则库（可选，默认自动加载）
    输出：
        (nine, six, three) 三个列表
    """
    if len(records) < 2:
        return [], [], []

    # 加载规则库（首次调用时）
    if rules_gold is None:
        rules_gold = load_rulebase("nv_双锚点规则库.json")
    if rules_3anchor is None:
        rules_3anchor = load_rulebase("nv_三锚点规则库.json")

    idx = len(records)
    prev = records[-1]
    cur_sx = prev["te_sx"]
    year = prev["lunar_year"]

    # 1. 遗漏值
    missing = {}
    for s in ZODIAC:
        streak = 0
        for i in range(idx - 1, -1, -1):
            if records[i]["te_sx"] != s:
                streak += 1
            else:
                break
        missing[s] = streak

    # 2. 当期各位置生肖
    sx_by_pos = {}
    for i, pn in enumerate(POS_NAMES):
        sx_by_pos[pn] = prev["te_sx"] if pn == "特码" else prev["ping_sx"][i]

    # 3. 金标投票（双锚点）
    gold_votes = Counter()
    te_kill_set = set()
    for ia in range(len(POS_NAMES)):
        pa = POS_NAMES[ia]
        sa = sx_by_pos[pa]
        for ib in range(ia + 1, len(POS_NAMES)):
            pb = POS_NAMES[ib]
            sb = sx_by_pos[pb]
            if pa < pb:
                anchor_sx = sa
            else:
                anchor_sx = sb
            anchor_idx = ZODIAC.index(anchor_sx)
            for off in OFFSETS:
                killed = ZODIAC[(anchor_idx + off) % 12]
                rule_key = f"{pa}:{sa}|{pb}:{sb}|{off}|{killed}"
                if rule_key in rules_gold:
                    gold_votes[killed] += 1
                    if pa == "特码" or pb == "特码":
                        te_kill_set.add(killed)

    # 4. 三锚点投票（权重 × ANCHOR3_WEIGHT）
    if rules_3anchor:
        for ia in range(len(POS_NAMES)):
            pa = POS_NAMES[ia]
            sa = sx_by_pos[pa]
            for ib in range(ia + 1, len(POS_NAMES)):
                pb = POS_NAMES[ib]
                sb = sx_by_pos[pb]
                for ic in range(ib + 1, len(POS_NAMES)):
                    pc = POS_NAMES[ic]
                    sc = sx_by_pos[pc]
                    ordered = sorted([(pa, sa), (pb, sb), (pc, sc)], key=lambda x: x[0])
                    key_str = f"{ordered[0][0]}:{ordered[0][1]}|{ordered[1][0]}:{ordered[1][1]}|{ordered[2][0]}:{ordered[2][1]}"
                    for killed in ZODIAC:
                        rule_key = key_str + "|" + killed
                        if rule_key in rules_3anchor:
                            gold_votes[killed] += ANCHOR3_WEIGHT

    # 5. 固定杀肖（平二+3 + 本期特肖）→ 降权扣分
    fixed_kill = set()
    p2_num = prev["ping_nums"][1]
    fixed_kill.add(get_shengxiao_by_suima(offset_num(p2_num, 3), year))
    fixed_kill.add(cur_sx)

    # 6. 冷却惩罚
    cool_map = {}
    for dist in range(1, COOL_WINDOW + 1):
        if idx - dist >= 0:
            sx = records[idx - dist]["te_sx"]
            pen = COOL_PENS[min(dist - 1, len(COOL_PENS) - 1)]
            if sx not in cool_map or pen > cool_map[sx]:
                cool_map[sx] = pen

    # 7. 平五+8 窗口
    oracle_pool = set()
    ping5 = prev["ping_nums"][4]
    center_num = (ping5 - 1 + 8) % 49 + 1
    center_sx = get_shengxiao_by_suima(center_num, year)
    center_idx = ZODIAC.index(center_sx)
    oracle_pool = set(ZODIAC[(center_idx + i) % 12] for i in range(-4, 5))

    # 8. 合冲池
    hechong_pool = get_hechong_full(cur_sx)

    # 9. 综合评分
    scores = {}
    for s in ZODIAC:
        # 遗漏值分段加权（正向）
        m = missing.get(s, 0)
        if m >= MISSING_THRESH[1]:
            score = m * MISSING_WEIGHTS[2]
        elif m >= MISSING_THRESH[0]:
            score = m * MISSING_WEIGHTS[1]
        else:
            score = m * MISSING_WEIGHTS[0]

        # 金标惩罚（反向）
        v = gold_votes.get(s, 0)
        if v >= 4:
            score -= int(GOLD_PENS[3] * GOLD_SCALE)
        elif v == 3:
            score -= int(GOLD_PENS[2] * GOLD_SCALE)
        elif v == 2:
            score -= int(GOLD_PENS[1] * GOLD_SCALE)
        elif v == 1:
            score -= int(GOLD_PENS[0] * GOLD_SCALE)

        # 特码金标杀肖扣分
        if s in te_kill_set:
            score -= TE_WEIGHT

        # 固定杀肖降权
        if s in fixed_kill:
            score -= FIXED_PENALTY

        # 冷却惩罚
        score -= cool_map.get(s, 0)

        # 平五窗口加分
        if s in oracle_pool:
            score += PING5_WEIGHT

        # 合冲池加分
        if s in hechong_pool:
            score += HECHONG_WEIGHT

        scores[s] = score

    # 10. 按得分降序排列
    sorted_sx = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    nine = [s for s, _ in sorted_sx[:9]]
    six = nine[:6]
    three = nine[:3]

    return nine, six, three


# ===================== 自检 =====================
if __name__ == "__main__":
    print("R96 反向杀肖模型自检")
    print("=" * 40)
    data = load_all_data(auto_update=False)
    records = extract_records_lunar(data)
    if len(records) >= 2:
        nine, six, three = predict_r96(records)
        latest = records[-1]
        print(f"基于期号: {latest['qishu']}")
        print(f"上期特肖: {latest['te_sx']}")
        print(f"九肖预测: {', '.join(nine)}")
        print(f"六肖预测: {', '.join(six)}")
        print(f"三肖预测: {', '.join(three)}")
    else:
        print("数据不足，无法预测。")