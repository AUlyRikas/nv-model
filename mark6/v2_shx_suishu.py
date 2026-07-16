#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2_shx_suishu.py —— 生肖岁数转换模块（修正农历跨年）
============================================================
核心功能：
  1. 根据公历开奖时间判断农历年（解决春节前后跨年问题）
  2. 获取某一农历年的本命生肖
  3. 号码（岁数）转生肖
  4. 生肖转号码列表（含本命年多出的 49 号）

数据基础：
  - 春节日期表 LUNAR_NEW_YEAR 硬编码了 2020~2031 年的正月初一公历日期。
  - 生肖顺序 SHENGXIAO 固定为 ["马","羊","猴","鸡","狗","猪","鼠","牛","虎","兔","龙","蛇"]。
  - 本命生肖基准：2026 年（马年）为参考点。

使用示例：
  >>> get_lunar_year("2025-01-28 21:35:00")   # 2025年春节1月29日，除夕 → 2024
  >>> get_benming(2024)                        # 龙
  >>> get_shengxiao_by_suima(1, 2024)          # 龙（本命年号码1为本命生肖）
  >>> get_suima_by_shengxiao("龙", 2024)       # [1,13,25,37,49]

注意：
  本模块仅依赖 Python 标准库，无外部依赖，可直接在任何环境中使用。
============================================================
"""

# ==================== 基础数据 ====================

SHENGXIAO = ["马", "羊", "猴", "鸡", "狗", "猪", "鼠", "牛", "虎", "兔", "龙", "蛇"]
"""12生肖顺序，以马开头（2026年本命）"""

LUNAR_NEW_YEAR = {
    2020: "01-25",
    2021: "02-12",
    2022: "02-01",
    2023: "01-22",
    2024: "02-10",
    2025: "01-29",
    2026: "02-17",
    2027: "02-06",
    2028: "01-26",
    2029: "02-13",
    2030: "02-03",
    2031: "01-23",
}
"""春节公历日期表（正月初一），格式 MM-DD，覆盖 2020~2031 年"""


# ==================== 农历年判断 ====================

def get_lunar_year(open_time_str):
    """
    根据开奖时间字符串返回农历年（生肖归属年）。

    参数:
        open_time_str (str): 开奖时间，格式 "YYYY-MM-DD HH:MM:SS"

    返回:
        int or None: 农历年份，若输入无效则返回 None

    逻辑:
        - 提取日期部分（YYYY-MM-DD）
        - 若日期 >= 当年春节日期 → 农历年 = 公历年
        - 若日期 < 当年春节日期 → 农历年 = 公历年 - 1
        - 这样处理完美避开农历大小月、闰月等复杂计算。
    """
    if not open_time_str or len(open_time_str) < 10:
        return None

    date_part = open_time_str[:10]          # "YYYY-MM-DD"
    try:
        year = int(date_part[:4])
    except ValueError:
        return None

    month_day = date_part[5:]               # "MM-DD"
    spring = LUNAR_NEW_YEAR.get(year, "01-01")  # 获取该年春节日期，默认1月1日

    if month_day >= spring:
        return year
    else:
        return year - 1


# ==================== 本命生肖 ====================

def get_benming(lunar_year):
    """
    获取某一农历年的本命生肖。

    参数:
        lunar_year (int): 农历年份

    返回:
        str: 本命生肖（如 "马"）

    原理:
        - 以 2026 年为基准（本命马），生肖列表索引 0
        - 年份每减 1，本命生肖在列表中逆时针移动一位（索引减 1 模 12）
    """
    base_year = 2026
    base_sx = "马"
    base_idx = SHENGXIAO.index(base_sx)     # 0
    diff = base_year - lunar_year
    idx = (base_idx - diff) % 12
    return SHENGXIAO[idx]


# ==================== 号码 ↔ 生肖映射 ====================

def get_shengxiao_by_suima(suima, lunar_year):
    """
    将号码（岁数）转换为生肖。

    参数:
        suima (int): 号码，1~49
        lunar_year (int): 农历年份

    返回:
        str: 对应的生肖

    算法:
        - 本命生肖对应的号码满足 (suima - 1) % 12 == 0
        - 号码每减 1，生肖在列表中逆时针移动一位
        - 公式: idx = (benming_idx - (suima - 1) % 12) % 12
    """
    benming = get_benming(lunar_year)
    benming_idx = SHENGXIAO.index(benming)
    offset = (suima - 1) % 12
    idx = (benming_idx - offset) % 12
    return SHENGXIAO[idx]


def get_suima_by_shengxiao(shengxiao, lunar_year):
    """
    获取某一农历年某生肖对应的所有号码。

    参数:
        shengxiao (str): 生肖名称
        lunar_year (int): 农历年份

    返回:
        list[int]: 号码列表（通常4个，本命年为5个，包含49）

    算法:
        - 先求目标生肖与本命生肖的索引差 offset
        - 基准号码 base = offset + 1（若 offset=0，则 base=1 为本命号码）
        - 四个号码为 base, base+12, base+24, base+36，均 ≤49
        - 若目标生肖为本命生肖且 49 不在列表中，则补入 49（本命年特例）
    """
    benming = get_benming(lunar_year)
    benming_idx = SHENGXIAO.index(benming)
    target_idx = SHENGXIAO.index(shengxiao)
    offset = (benming_idx - target_idx) % 12
    base = offset + 1
    numbers = [base, base + 12, base + 24, base + 36]
    # 本命生肖多一个 49 号
    if shengxiao == benming and 49 not in numbers:
        numbers.append(49)
    # 确保所有号码在 1~49 范围内
    return [n if n <= 49 else n - 48 for n in numbers]


# ==================== 自检 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("v2_shx_suishu.py 自检")
    print("=" * 60)

    # 1. 春节日期表
    print("\n[春节日期表]")
    for y in range(2020, 2032):
        print(f"  {y}: {LUNAR_NEW_YEAR.get(y, '?')}")

    # 2. 农历年判断
    print("\n[农历年判断]")
    tests = [
        ("2025-01-28 21:35:00", 2024),
        ("2025-01-29 21:35:00", 2025),
        ("2026-02-16 21:35:00", 2025),
        ("2026-02-17 21:35:00", 2026),
        ("", None),
        ("abc", None),
    ]
    for ot, exp in tests:
        res = get_lunar_year(ot)
        status = "✓" if res == exp else "✗"
        print(f"  {ot[:10] if ot else '(空)'} → {res} (预期{exp}) {status}")

    # 3. 本命生肖
    print("\n[本命生肖]")
    for y, exp in [(2024, "龙"), (2025, "蛇"), (2026, "马")]:
        res = get_benming(y)
        status = "✓" if res == exp else "✗"
        print(f"  {y}年 → {res} (预期{exp}) {status}")

    # 4. 号码转生肖
    print("\n[号码转生肖]")
    for (y, num, exp) in [
        (2024, 1, "龙"), (2024, 2, "兔"), (2024, 13, "龙"), (2024, 49, "龙"),
        (2025, 1, "蛇"), (2025, 2, "龙"), (2025, 13, "蛇"),
    ]:
        res = get_shengxiao_by_suima(num, y)
        status = "✓" if res == exp else "✗"
        print(f"  {y}年 号码{num:2d} → {res} (预期{exp}) {status}")

    # 5. 生肖转号码
    print("\n[生肖转号码]")
    for (y, sx, exp) in [
        (2024, "龙", [1,13,25,37,49]), (2024, "兔", [2,14,26,38]),
        (2025, "蛇", [1,13,25,37,49]), (2025, "龙", [2,14,26,38]),
    ]:
        res = sorted(get_suima_by_shengxiao(sx, y))
        status = "✓" if res == sorted(exp) else "✗"
        print(f"  {y}年 {sx} → {res} (预期{exp}) {status}")

    print("\n" + "=" * 60)
    print("自检完成")
    print("=" * 60)