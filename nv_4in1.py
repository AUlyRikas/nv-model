#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nv_4in1.py —— 四合一集成投票引擎（最终版）
============================================================
模型构成：
  M1  (nv_m1.py)        — 外部锚点规律 + 不等权投票 + F5微调
  P54 (nv_p54.py)       — 54条围肖信号等权投票 + 冷号优先
  R96 (nv_r96.py)       — 规则库反向杀肖评分（仅提供金标安全分）

集成机制：
  1. 三个子模型各输出9肖
  2. 等权投票 + 非线性排名得分（前3=9分/4-6=3分/7-9=1分）
  3. 金标安全分：双锚点+三锚点规则库联合计算
  4. 非线性惩罚：被杀≥2次的生肖，安全分×3

排序规则：
  九肖：票数 → 排名得分 → 遗漏值
  六肖：票数 → 排名得分 → 安全分(原版) → 遗漏值
  五肖：票数 → 惩罚安全分(升序) → 遗漏值（独立排序）
  四肖：票数 → 惩罚安全分(升序) → 遗漏值（独立排序）
  三肖：票数 → 惩罚安全分(升序) → 遗漏值（独立排序）

新增功能：
  - 优化版7尾：基于三肖尾数频次 + 近5期热尾，每期动态生成
  - 16码生成：沿用旧版V5.1逻辑（三肖强制入选 + 六肖补齐）

用法：
  python nv_4in1.py          → 屏幕预测
  python nv_4in1.py --test   → 回测验证（样本外，含7尾和16码）
  python nv_4in1.py --output → 输出 JS 数据文件 + 保存记录
============================================================
"""

import json
import os
import sys
from collections import Counter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MARK6_DIR = os.path.join(BASE_DIR, "mark6")
if MARK6_DIR not in sys.path:
    sys.path.insert(0, MARK6_DIR)

from v2_shx_suishu import (
    SHENGXIAO, get_lunar_year, get_shengxiao_by_suima, get_suima_by_shengxiao
)
from shuju_loader import load_all_data

from nv_m1 import predict_m1
from nv_p54 import predict_p54
from nv_r96 import predict_r96, load_rulebase

ZODIAC = SHENGXIAO
POS_NAMES = ["平一", "平二", "平三", "平四", "平五", "平六", "特码"]


def extract_records_lunar(data):
    """提取标准记录，包含te_tail字段"""
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
                "te_tail": nums[6] % 10,
                "ping_nums": nums[:6],
                "ping_sx": [get_shengxiao_by_suima(n, lunar_year) for n in nums[:6]],
            })
        except:
            continue
    records.sort(key=lambda x: int(x["qishu"]))
    return records


def compute_gold_safety(prev, rules_gold, rules_3anchor=None):
    safety = Counter()
    sx_by_pos = {}
    for i, pn in enumerate(POS_NAMES):
        sx_by_pos[pn] = prev["te_sx"] if pn == "特码" else prev["ping_sx"][i]
    for ia in range(len(POS_NAMES)):
        pa = POS_NAMES[ia]; sa = sx_by_pos[pa]
        for ib in range(ia + 1, len(POS_NAMES)):
            pb = POS_NAMES[ib]; sb = sx_by_pos[pb]
            if pa < pb: anchor_sx = sa
            else: anchor_sx = sb
            anchor_idx = ZODIAC.index(anchor_sx)
            for off in range(-5, 7):
                killed = ZODIAC[(anchor_idx + off) % 12]
                rule_key = f"{pa}:{sa}|{pb}:{sb}|{off}|{killed}"
                if rule_key in rules_gold:
                    safety[killed] += 1
    if rules_3anchor:
        for ia in range(len(POS_NAMES)):
            pa = POS_NAMES[ia]; sa = sx_by_pos[pa]
            for ib in range(ia + 1, len(POS_NAMES)):
                pb = POS_NAMES[ib]; sb = sx_by_pos[pb]
                for ic in range(ib + 1, len(POS_NAMES)):
                    pc = POS_NAMES[ic]; sc = sx_by_pos[pc]
                    ordered = sorted([(pa, sa), (pb, sb), (pc, sc)], key=lambda x: x[0])
                    key_str = f"{ordered[0][0]}:{ordered[0][1]}|{ordered[1][0]}:{ordered[1][1]}|{ordered[2][0]}:{ordered[2][1]}"
                    for killed in ZODIAC:
                        rule_key = key_str + "|" + killed
                        if rule_key in rules_3anchor:
                            safety[killed] += 1
    return safety


def penalize_safety(raw_safety, threshold=2, factor=3):
    penalized = {}
    for s in ZODIAC:
        raw = raw_safety.get(s, 0)
        if raw >= threshold:
            penalized[s] = raw * factor
        else:
            penalized[s] = raw
    return penalized


def get_optimized_tails(records, idx, three_sx, year):
    hist = records[:idx]
    tail_counter = Counter()
    for sx in three_sx:
        for n in get_suima_by_shengxiao(sx, year):
            tail_counter[n % 10] += 1
    three_top = [t for t, _ in tail_counter.most_common()]
    lookback = min(5, idx - 1)
    freq = Counter()
    for i in range(idx - lookback, idx):
        if i >= 0:
            freq[hist[i]["te_tail"]] += 1
    hot_tails = sorted(range(10), key=lambda t: (-freq.get(t, 0), t))
    result = []
    for t in three_top:
        if t not in result:
            result.append(t)
    for t in hot_tails:
        if t not in result:
            result.append(t)
        if len(result) >= 7:
            break
    return result[:7]


def old_16code(records, idx, six_sx, three_sx, anchor_sx):
    hist = records[:idx]
    prev = hist[-1]
    year = prev["lunar_year"]
    three_nums = set()
    for sx in three_sx:
        for n in get_suima_by_shengxiao(sx, year):
            three_nums.add(n)
    num_missing = {}
    for n in range(1, 50):
        streak = 0
        for i in range(idx - 1, -1, -1):
            if hist[i]["te_num"] != n:
                streak += 1
            else:
                break
        num_missing[n] = streak
    if len(three_nums) >= 16:
        return sorted(three_nums, key=lambda n: -num_missing.get(n, 0))[:16]
    result = list(three_nums)
    TAIL_TABLE = {
        "马": [0,1,2,3,4,7,8], "羊": [1,2,3,4,6,7,8], "猴": [1,2,4,5,6,8,9],
        "鸡": [0,2,3,4,6,8,9], "狗": [0,1,2,3,5,6,7], "猪": [1,3,4,5,6,7,8],
        "鼠": [0,1,3,4,6,7,9], "牛": [0,1,3,5,6,7,8], "虎": [1,4,5,6,7,8,9],
        "兔": [0,1,2,3,4,6,8], "龙": [0,1,2,3,4,5,6], "蛇": [1,2,3,4,6,7,8],
    }
    opt_tails_anchor = set(TAIL_TABLE.get(anchor_sx, list(range(7))))
    lookback = min(10, idx - 1)
    freq = Counter()
    for i in range(idx - lookback, idx):
        if i >= 0:
            freq[hist[i]["te_tail"]] += 1
    dyn_cold = sorted(range(10), key=lambda t: (freq.get(t, 0), t))[:7]
    priority_tails = opt_tails_anchor & set(dyn_cold)
    if not priority_tails:
        priority_tails = opt_tails_anchor
    seen = set(result)
    six_candidates = []
    for sx in six_sx:
        for n in get_suima_by_shengxiao(sx, year):
            if n not in seen:
                six_candidates.append(n)
                seen.add(n)
    def sort_key(n):
        is_priority = 0 if n % 10 in priority_tails else 1
        is_anchor = 0 if n % 10 in opt_tails_anchor else 1
        return (is_priority, is_anchor, -num_missing.get(n, 0))
    six_candidates.sort(key=sort_key)
    for n in six_candidates:
        if len(result) >= 16:
            break
        result.append(n)
    if len(result) < 16:
        existing = set(result)
        all_sorted = sorted(range(1, 50), key=lambda n: -num_missing.get(n, 0))
        for n in all_sorted:
            if n not in existing:
                result.append(n)
                if len(result) >= 16:
                    break
    return result[:16]


def ensemble_predict(records, rules_gold=None, rules_3anchor=None):
    if len(records) < 2:
        return [], [], [], [], []
    if rules_gold is None:
        rules_gold = load_rulebase("nv_双锚点规则库.json")
    if rules_3anchor is None:
        rules_3anchor = load_rulebase("nv_三锚点规则库.json")
    m1_nine, _, _ = predict_m1(records)
    p54_nine, _, _ = predict_p54(records)
    r96_nine, _, _ = predict_r96(records, rules_gold, rules_3anchor)
    idx = len(records)
    missing = {}
    for s in ZODIAC:
        streak = 0
        for i in range(idx - 1, -1, -1):
            if records[i]["te_sx"] != s:
                streak += 1
            else:
                break
        missing[s] = streak
    def fill(nine):
        return nine if nine else sorted(ZODIAC, key=lambda x: missing.get(x, 0), reverse=True)[:9]
    m1_nine = fill(m1_nine)
    p54_nine = fill(p54_nine)
    r96_nine = fill(r96_nine)
    rank_scores = Counter()
    votes = Counter()
    for nine in [m1_nine, p54_nine, r96_nine]:
        for rank, s in enumerate(nine):
            if rank < 3:
                rank_scores[s] += 9
            elif rank < 6:
                rank_scores[s] += 3
            else:
                rank_scores[s] += 1
            votes[s] += 1
    prev = records[-1]
    raw_safety = compute_gold_safety(prev, rules_gold, rules_3anchor)
    pen_safety = penalize_safety(raw_safety, threshold=2, factor=3)
    nine_ranked = sorted(votes.items(), key=lambda x: (
        -x[1], -rank_scores.get(x[0], 0), -missing.get(x[0], 0)
    ))
    nine_sx = [s for s, _ in nine_ranked[:9]]
    six_ranked = sorted(votes.items(), key=lambda x: (
        -x[1], -rank_scores.get(x[0], 0),
        raw_safety.get(x[0], 99), -missing.get(x[0], 0)
    ))
    six_sx = [s for s, _ in six_ranked[:6]]
    five_ranked = sorted(votes.items(), key=lambda x: (
        -x[1], pen_safety.get(x[0], 99), -missing.get(x[0], 0)
    ))
    five_sx = [s for s, _ in five_ranked[:5]]
    four_ranked = sorted(votes.items(), key=lambda x: (
        -x[1], pen_safety.get(x[0], 99), -missing.get(x[0], 0)
    ))
    four_sx = [s for s, _ in four_ranked[:4]]
    three_ranked = sorted(votes.items(), key=lambda x: (
        -x[1], pen_safety.get(x[0], 99), -missing.get(x[0], 0)
    ))
    three_sx = [s for s, _ in three_ranked[:3]]
    return nine_sx, six_sx, five_sx, four_sx, three_sx


def evaluate_ensemble(records, start, end, rules_gold, rules_3anchor):
    hits = {k: [] for k in [9, 6, 5, 4, 3]}
    hits_7tail = []
    hits_16code = []
    for idx in range(start, end):
        hist = records[:idx]
        nine, six, five, four, three = ensemble_predict(hist, rules_gold, rules_3anchor)
        actual_sx = records[idx]["te_sx"]
        actual_num = records[idx]["te_num"]
        actual_tail = actual_num % 10
        year = records[idx]["lunar_year"]
        anchor_sx = records[idx - 1]["ping_sx"][1]
        hits[9].append(1 if actual_sx in nine else 0)
        hits[6].append(1 if actual_sx in six else 0)
        hits[5].append(1 if actual_sx in five else 0)
        hits[4].append(1 if actual_sx in four else 0)
        hits[3].append(1 if actual_sx in three else 0)
        tails7 = get_optimized_tails(records, idx, three, year)
        hits_7tail.append(1 if actual_tail in tails7 else 0)
        codes16 = old_16code(records, idx, six, three, anchor_sx)
        hits_16code.append(1 if actual_num in codes16 else 0)
    def calc(lst):
        total = len(lst)
        rate = sum(lst) / total * 100 if total else 0
        cur, ms, dist = 0, 0, Counter()
        for h in lst:
            if h == 0:
                cur += 1
                ms = max(ms, cur)
            else:
                if cur > 0:
                    dist[cur] += 1
                cur = 0
        if cur > 0:
            dist[cur] += 1
        return rate, ms, dict(sorted(dist.items()))
    results = {}
    for k in [9, 6, 5, 4, 3]:
        r, ms, d = calc(hits[k])
        results[k] = (r, ms, d)
    r7, ms7, d7 = calc(hits_7tail)
    results['7tail'] = (r7, ms7, d7)
    r16, ms16, d16 = calc(hits_16code)
    results['16code'] = (r16, ms16, d16)
    return results


if __name__ == "__main__":
    import argparse
    from datetime import datetime

    parser = argparse.ArgumentParser(description="四合一集成投票引擎")
    parser.add_argument("--test", action="store_true", help="回测验证（样本外 2001~最后）")
    parser.add_argument("--output", action="store_true", help="输出 JS 数据文件并保存预测记录")
    args = parser.parse_args()

    print("加载数据...")
    data = load_all_data(auto_update=False)
    records = extract_records_lunar(data)
    total = len(records)
    print(f"总期数: {total}")

    rules_gold = load_rulebase("nv_双锚点规则库.json")
    rules_3anchor = load_rulebase("nv_三锚点规则库.json")

    if args.test:
        print(f"\n=== 集成回测（样本外 2001~{total}） ===")
        results = evaluate_ensemble(records, 2001, total, rules_gold, rules_3anchor)
        for k in [9, 6, 5, 4, 3]:
            label = f"{k}肖"
            r, ms, d = results[k]
            print(f"{label}: 命中率 {r:.2f}% | 最大连错 {ms}期 | 连错分布 {d}")
        r7, ms7, d7 = results['7tail']
        print(f"7尾:  命中率 {r7:.2f}% | 最大连错 {ms7}期 | 连错分布 {d7}")
        r16, ms16, d16 = results['16code']
        print(f"16码: 命中率 {r16:.2f}% | 最大连错 {ms16}期 | 连错分布 {d16}")
        sys.exit(0)

    if args.output:
        latest_data = data[-1] if data else {}
        nine, six, five, four, three = ensemble_predict(records, rules_gold, rules_3anchor)
        prev = records[-1]
        year = prev["lunar_year"]
        anchor_sx = prev["ping_sx"][1]
        tails7 = get_optimized_tails(records, len(records), three, year)
        codes16 = old_16code(records, len(records), six, three, anchor_sx)
        js_data = {
            "time": latest_data.get("openTime", ""),
            "issue": prev["qishu"],
            "code": latest_data.get("openCode", ""),
            "zodiac": latest_data.get("zodiac", ""),
            "wave": latest_data.get("wave", ""),
            "teSx": prev["te_sx"],
            "teWei": prev.get("te_tail", prev["te_num"] % 10),
            "nextIssue": "",
            "ninePool": nine,
            "sixPool": six,
            "five": five,
            "four": four,
            "three": three,
            "pools": {3: three, 4: four, 5: five},
            "optTails": tails7,
            "numbers": codes16,
            "killZodiacs": [],
        }
        try:
            exp = prev["qishu"]
            if len(exp) >= 4:
                js_data["nextIssue"] = f"{exp[:4]}{int(exp[-3:]) + 1:03d}"
        except:
            pass
        js_path = os.path.join(BASE_DIR, "ensemble_data_v6.js")
        with open(js_path, "w", encoding="utf-8") as f:
            f.write("var ensembleData = ")
            json.dump(js_data, f, ensure_ascii=False, indent=2)
            f.write(";")
        print(f"[V6] ensemble_data_v6.js 已更新")
        record_dir = os.path.join(BASE_DIR, "oracle记录")
        os.makedirs(record_dir, exist_ok=True)
        record_path = os.path.join(record_dir, "ensemble_v6_history.txt")
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        next_issue = js_data.get("nextIssue", "")
        already_saved = False
        if os.path.exists(record_path):
            with open(record_path, "r", encoding="utf-8") as f:
                if f"预测下期: {next_issue}" in f.read():
                    already_saved = True
        if not already_saved:
            text = f"""
{'='*50}
{now_str}
基于期号: {prev['qishu']}
开奖时间: {latest_data.get('openTime', '')}
开奖号码: {latest_data.get('openCode', '')}
本期特肖: {prev['te_sx']}
预测下期: {next_issue}
{'-'*30}
★九肖: {', '.join(nine)}
★六肖: {', '.join(six)}
★五肖: {', '.join(five)}
★四肖: {', '.join(four)}
★三肖: {', '.join(three)}
★16码: {' '.join(str(n) for n in codes16)}
★最优7尾: {' '.join(str(t) for t in tails7)}
{'='*50}
"""
            with open(record_path, "a", encoding="utf-8") as f:
                f.write(text)
            print(f"记录已保存至 {record_path}")
        else:
            print(f"期号 {next_issue} 已有记录，跳过保存")
        sys.exit(0)

    # 默认：屏幕预测
    nine, six, five, four, three = ensemble_predict(records, rules_gold, rules_3anchor)
    latest = records[-1]
    year = latest["lunar_year"]
    anchor_sx = latest["ping_sx"][1]
    tails7 = get_optimized_tails(records, len(records), three, year)
    codes16 = old_16code(records, len(records), six, three, anchor_sx)

    print(f"基于期号: {latest['qishu']}")
    print(f"上期特肖: {latest['te_sx']}")
    print(f"九肖预测: {', '.join(nine)}")
    print(f"六肖预测: {', '.join(six)}")
    print(f"五肖预测: {', '.join(five)}")
    print(f"四肖预测: {', '.join(four)}")
    print(f"三肖预测: {', '.join(three)}")
    print(f"16码: {' '.join(str(n) for n in codes16)}")
    print(f"最优7尾: {' '.join(str(t) for t in tails7)}")