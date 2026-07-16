#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nv_双锚点规则库_生成器_v2.py —— 双锚点金标规则库生成器（最终版）
============================================================
功能：
  在训练集（前2000期）上生成双锚点杀肖规则，规则格式为：
  位置A:生肖A | 位置B:生肖B | 偏移量 | 被杀生肖
  覆盖所有21种位置对，偏移量 -5~+6（12个唯一偏移），
  训练集筛选条件：样本量 ≥ 15，杀中率 ≥ 96%，最大连错 ≤ 1。
  之后在样本外（2001~最后一期）逐条验证连错，剔除连错 > 1 的规则。
  最终输出 nv_双锚点规则库.json。

使用说明：
  - 只依赖 v2_shx_suishu 和 shuju_loader，不修改任何生产文件。
  - 运行一次即可生成最终规则库，覆盖前2000期训练。
============================================================
"""

import json, os, sys
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MARK6_DIR = os.path.join(BASE_DIR, "mark6")
sys.path.insert(0, MARK6_DIR)

# 农历年生肖转换（只读）
from v2_shx_suishu import SHENGXIAO, get_lunar_year, get_shengxiao_by_suima
# 数据加载（只读）
from shuju_loader import load_all_data

ZODIAC = SHENGXIAO                    # 12生肖列表
POS_NAMES = ["平一", "平二", "平三", "平四", "平五", "平六", "特码"]
OFFSETS = list(range(-5, 7))          # 12个唯一生肖偏移，无重复

# ---------- 规则库构建参数 ----------
MIN_SAMPLES = 15                      # 训练集最小样本量
MIN_KILL_RATE = 96.0                  # 训练集最低杀中率（%）
MAX_CONSECUTIVE_TRAIN = 1             # 训练集最大连错次数
MAX_CONSECUTIVE_TEST = 1              # 样本外允许的最大连错（超过则剔除）


def extract_records_lunar(data):
    """
    从原始数据中提取记录，使用农历年计算所有生肖。
    """
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


def check_rule_in_test(records, test_start, test_end,
                       pa, sa, pb, sb, anchor_idx, off):
    """
    在样本外区间逐期验证一条规则的连错。
    返回: (杀中率, 最大连错, 触发次数)
    """
    total_count = 0
    hit_count = 0
    max_streak = 0
    cur_streak = 0

    for idx in range(test_start, test_end):
        prev = records[idx - 1]
        nxt = records[idx]
        sx_by_pos = {}
        for i, pn in enumerate(POS_NAMES):
            sx_by_pos[pn] = prev["te_sx"] if pn == "特码" else prev["ping_sx"][i]

        # 检查是否匹配锚点条件
        if sx_by_pos[pa] == sa and sx_by_pos[pb] == sb:
            total_count += 1
            killed = ZODIAC[(anchor_idx + off) % 12]
            if nxt["te_sx"] != killed:
                hit_count += 1
                cur_streak = 0
            else:
                cur_streak += 1
                max_streak = max(max_streak, cur_streak)

    if total_count == 0:
        return 0, 0, 0
    kill_rate = hit_count / total_count * 100.0
    return kill_rate, max_streak, total_count


def build_rules(records):
    """
    主构建函数：先生成候选规则（训练集筛选），再样本外剔除连错>1。
    """
    train_end = 2000
    test_start = 2001
    test_end = len(records)

    # ---------- 第一步：收集训练集统计信息 ----------
    stats = defaultdict(list)  # key=(pa,sa,pb,sb) -> list of 下期特肖
    for i in range(train_end - 1):
        curr = records[i]
        nxt = records[i + 1]
        sx_by_pos = {}
        for idx, pn in enumerate(POS_NAMES):
            sx_by_pos[pn] = curr["te_sx"] if pn == "特码" else curr["ping_sx"][idx]

        for ia in range(len(POS_NAMES)):
            pa = POS_NAMES[ia]
            sa = sx_by_pos[pa]
            for ib in range(ia + 1, len(POS_NAMES)):
                pb = POS_NAMES[ib]
                sb = sx_by_pos[pb]
                # 统一按位置名字典序排列，保证唯一键
                if pa < pb:
                    key = (pa, sa, pb, sb)
                else:
                    key = (pb, sb, pa, sa)
                stats[key].append(nxt["te_sx"])

    # ---------- 第二步：生成候选规则（训练集条件筛选） ----------
    candidates = []  # 存储 (rule_key, rule_dict, anchor_idx)
    for (pa, sa, pb, sb), next_list in stats.items():
        total = len(next_list)
        if total < MIN_SAMPLES:
            continue

        # 确定锚点生肖（从字典序靠前的锚点偏移）
        if pa < pb:
            anchor_sx = sa
        else:
            anchor_sx = sb
        anchor_idx = ZODIAC.index(anchor_sx)

        # 对12个偏移逐一评估
        for off in OFFSETS:
            killed_sx = ZODIAC[(anchor_idx + off) % 12]
            miss_count = next_list.count(killed_sx)
            hit_count = total - miss_count
            kill_rate = hit_count / total * 100.0

            # 计算最大连错
            max_streak = 0
            cur_streak = 0
            for sx_ in next_list:
                if sx_ == killed_sx:
                    cur_streak += 1
                    max_streak = max(max_streak, cur_streak)
                else:
                    cur_streak = 0

            if kill_rate >= MIN_KILL_RATE and max_streak <= MAX_CONSECUTIVE_TRAIN:
                rule_key = f"{pa}:{sa}|{pb}:{sb}|{off}|{killed_sx}"
                rule_dict = {
                    "grade": "gold",
                    "train_rate": round(kill_rate, 2),
                    "train_total": total,
                    "samples": total,
                    "anchor_a": f"{pa}:{sa}",
                    "anchor_b": f"{pb}:{sb}",
                    "offset": off,
                    "killed_sx": killed_sx,
                    # 样本外字段先占位，后续填充
                    "test_rate": None,
                    "test_total": 0,
                    "test_streak": None
                }
                candidates.append((rule_key, rule_dict, anchor_idx))

    print(f"训练集候选规则: {len(candidates)} 条")

    # ---------- 第三步：样本外逐条验证，剔除连错 > 1 ----------
    rules_final = {}
    passed, failed = 0, 0
    for rule_key, rule_dict, anchor_idx in candidates:
        # 提取锚点信息
        parts = rule_key.split("|")
        # parts[0] 格式: "平一:虎"， parts[1]: "平四:龙"
        anchor_a = parts[0].split(":")
        anchor_b = parts[1].split(":")
        pa, sa = anchor_a[0], anchor_a[1]
        pb, sb = anchor_b[0], anchor_b[1]
        off = int(parts[2])
        killed_sx = parts[3]

        test_rate, test_streak, test_total = check_rule_in_test(
            records, test_start, test_end,
            pa, sa, pb, sb, anchor_idx, off
        )

        if test_streak > MAX_CONSECUTIVE_TEST:
            failed += 1
            continue

        # 更新样本外信息
        rule_dict["test_rate"] = round(test_rate, 2) if test_total > 0 else None
        rule_dict["test_total"] = test_total
        rule_dict["test_streak"] = test_streak
        rules_final[rule_key] = rule_dict
        passed += 1

    print(f"通过样本外验证: {passed} 条，剔除: {failed} 条")
    return rules_final


if __name__ == "__main__":
    print("=" * 60)
    print("双锚点金标规则库生成器 v2")
    print("=" * 60)

    print("加载全量数据...")
    data = load_all_data(auto_update=False)
    records = extract_records_lunar(data)
    print(f"总期数: {len(records)}")

    print("\n开始构建规则库...")
    rules = build_rules(records)

    # 保存
    output_path = os.path.join(BASE_DIR, "nv_双锚点规则库.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)
    print(f"\n最终规则数: {len(rules)}")
    print(f"规则库已保存至: {output_path}")