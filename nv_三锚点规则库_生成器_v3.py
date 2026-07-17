#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nv_三锚点规则库_生成器_v3.py —— 三锚点超金标规则库生成器（最终版）
============================================================
功能：
  在训练集（前2000期）上生成三锚点杀肖规则，规则格式为：
  位置A:生肖A | 位置B:生肖B | 位置C:生肖C | 被杀生肖
  覆盖所有35种位置三元组（C(7,3)=35），使用频率统计法：
  - 训练集：样本量 ≥ 3，被杀生肖在下期特肖中出现频率 ≤ 5%，最大连错 ≤ 1。
  - 样本外：触发次数 ≥ 1，杀中率 ≥ 93%，最大连错 ≤ 1。
  最终输出 nv_三锚点规则库.json。

设计原则：
  - 三锚点规则条件苛刻，因此训练集门槛比双锚点低。
  - 样本外验证确保实际使用时的高置信度。
  - 独立规则库，不与双锚点合并，方便分别调用。
============================================================
"""

import json, os, sys
from collections import defaultdict, Counter
from itertools import combinations

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MARK6_DIR = os.path.join(BASE_DIR, "mark6")
sys.path.insert(0, MARK6_DIR)

from v2_shx_suishu import SHENGXIAO, get_lunar_year, get_shengxiao_by_suima
from shuju_loader import load_all_data

ZODIAC = SHENGXIAO
POS_NAMES = ["平一", "平二", "平三", "平四", "平五", "平六", "特码"]

# ---------- 规则库构建参数 ----------
MIN_SAMPLES_TRAIN = 3                # 训练集最小样本量
MAX_KILL_FREQ = 0.05                 # 被杀生肖最大出现频率
MAX_CONSECUTIVE_TRAIN = 1            # 训练集最大连错
MIN_TEST_SAMPLES = 1                 # 样本外最低触发次数
MIN_TEST_RATE = 93.0                 # 样本外最低杀中率(%)
MAX_CONSECUTIVE_TEST = 1             # 样本外最大连错


def extract_records_lunar(data):
    records = []
    for item in data:
        try:
            qs = str(item.get("expect", ""))
            oc = str(item.get("openCode", ""))
            ot = item.get("openTime", "")
            if not qs or not oc: continue
            parts = oc.strip().split(",")
            if len(parts) != 7: continue
            nums = [int(p.strip()) for p in parts]
            lunar_year = get_lunar_year(ot)
            if lunar_year is None: continue
            records.append({
                "qishu": qs, "lunar_year": lunar_year,
                "te_num": nums[6],
                "te_sx": get_shengxiao_by_suima(nums[6], lunar_year),
                "ping_nums": nums[:6],
                "ping_sx": [get_shengxiao_by_suima(n, lunar_year) for n in nums[:6]],
            })
        except: continue
    records.sort(key=lambda x: int(x["qishu"]))
    return records


def evaluate_rule_in_test(records, test_start, test_end,
                          pa, sa, pb, sb, pc, sc, killed_sx):
    """单条三锚点规则在样本外评估，返回(触发次数, 杀中率, 最大连错)"""
    total = 0
    hits = 0
    cur_streak = 0
    max_streak = 0
    for idx in range(test_start, test_end):
        prev = records[idx - 1]
        actual = records[idx]["te_sx"]
        sx_by_pos = {}
        for i, pn in enumerate(POS_NAMES):
            sx_by_pos[pn] = prev["te_sx"] if pn == "特码" else prev["ping_sx"][i]
        if sx_by_pos[pa] == sa and sx_by_pos[pb] == sb and sx_by_pos[pc] == sc:
            total += 1
            if actual != killed_sx:
                hits += 1
                cur_streak = 0
            else:
                cur_streak += 1
                max_streak = max(max_streak, cur_streak)
    rate = hits / total * 100 if total > 0 else 0
    return total, rate, max_streak


def build_rules(records):
    train_end = 2000
    test_start = 2001
    test_end = len(records)
    pos_triplets = list(combinations(range(7), 3))  # 35种位置三元组

    # ---------- 第一步：训练集统计 ----------
    stats = defaultdict(list)
    for i in range(train_end - 1):
        curr = records[i]
        nxt = records[i + 1]
        sx_by_pos = {}
        for idx, pn in enumerate(POS_NAMES):
            sx_by_pos[pn] = curr["te_sx"] if pn == "特码" else curr["ping_sx"][idx]

        for (ia, ib, ic) in pos_triplets:
            pa, pb, pc = POS_NAMES[ia], POS_NAMES[ib], POS_NAMES[ic]
            sa, sb, sc = sx_by_pos[pa], sx_by_pos[pb], sx_by_pos[pc]
            # 按位置名字典序统一键
            ordered = sorted([(pa, sa), (pb, sb), (pc, sc)], key=lambda x: x[0])
            key = (ordered[0][0], ordered[0][1],
                   ordered[1][0], ordered[1][1],
                   ordered[2][0], ordered[2][1])
            stats[key].append(nxt["te_sx"])

    # ---------- 第二步：生成候选规则 ----------
    candidates = []
    for (pa, sa, pb, sb, pc, sc), next_list in stats.items():
        total = len(next_list)
        if total < MIN_SAMPLES_TRAIN:
            continue
        freq = Counter(next_list)
        for killed_sx in ZODIAC:
            kill_freq = freq.get(killed_sx, 0) / total
            if kill_freq > MAX_KILL_FREQ:
                continue
            # 检查最大连错
            max_streak = 0
            cur_streak = 0
            for sx_ in next_list:
                if sx_ == killed_sx:
                    cur_streak += 1
                    max_streak = max(max_streak, cur_streak)
                else:
                    cur_streak = 0
            if max_streak <= MAX_CONSECUTIVE_TRAIN:
                rule_key = f"{pa}:{sa}|{pb}:{sb}|{pc}:{sc}|{killed_sx}"
                rule_dict = {
                    "grade": "gold",
                    "train_samples": total,
                    "train_kill_freq": round(kill_freq * 100, 2),
                    "killed_sx": killed_sx,
                    "anchors": f"{pa}:{sa}, {pb}:{sb}, {pc}:{sc}"
                }
                candidates.append((rule_key, rule_dict, (pa, sa, pb, sb, pc, sc)))

    print(f"训练集候选规则: {len(candidates)} 条")

    # ---------- 第三步：样本外验证 ----------
    rules_final = {}
    passed, failed = 0, 0
    for rule_key, rule_dict, (pa, sa, pb, sb, pc, sc) in candidates:
        killed_sx = rule_dict["killed_sx"]
        test_tot, test_rate, test_streak = evaluate_rule_in_test(
            records, test_start, test_end,
            pa, sa, pb, sb, pc, sc, killed_sx
        )
        if test_tot < MIN_TEST_SAMPLES or test_rate < MIN_TEST_RATE or test_streak > MAX_CONSECUTIVE_TEST:
            failed += 1
            continue
        rule_dict["test_samples"] = test_tot
        rule_dict["test_rate"] = round(test_rate, 2)
        rule_dict["test_streak"] = test_streak
        rules_final[rule_key] = rule_dict
        passed += 1

    print(f"通过样本外验证: {passed} 条，剔除: {failed} 条")
    return rules_final


if __name__ == "__main__":
    print("=" * 60)
    print("三锚点超金标规则库生成器 v3")
    print("=" * 60)

    print("加载全量数据...")
    data = load_all_data(auto_update=False)
    records = extract_records_lunar(data)
    print(f"总期数: {len(records)}")

    print("\n开始构建规则库...")
    rules = build_rules(records)

    output_path = os.path.join(BASE_DIR, "nv_三锚点规则库.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)
    print(f"\n最终规则数: {len(rules)}")
    print(f"规则库已保存至: {output_path}")