"""
杨永兴短线战法 - 持仓跟踪管理
"""

import json
import os
import datetime
from config import PORTFOLIO_FILE, WATCHLIST_FILE


def load_json(filepath):
    """加载JSON文件"""
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(filepath, data):
    """保存JSON文件"""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============ 持仓管理 ============

def get_portfolio():
    """获取当前持仓"""
    return load_json(PORTFOLIO_FILE)


def add_position(code, name, buy_price, buy_date=None, notes=""):
    """添加持仓"""
    if buy_date is None:
        buy_date = datetime.date.today().strftime("%Y-%m-%d")

    portfolio = load_json(PORTFOLIO_FILE)

    # 检查是否已存在
    for pos in portfolio:
        if pos.get("code") == code:
            print(f"⚠️ {code} {name} 已在持仓中")
            return False

    portfolio.append({
        "code": code,
        "name": name,
        "buy_price": float(buy_price),
        "buy_date": buy_date,
        "notes": notes,
        "added_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    save_json(PORTFOLIO_FILE, portfolio)
    print(f"✅ 已添加 {code} {name}，买入价 {buy_price}")
    return True


def remove_position(code):
    """移除持仓"""
    portfolio = load_json(PORTFOLIO_FILE)
    new_portfolio = [p for p in portfolio if p.get("code") != code]

    if len(new_portfolio) == len(portfolio):
        print(f"⚠️ {code} 不在持仓中")
        return False

    removed = [p for p in portfolio if p.get("code") == code]
    save_json(PORTFOLIO_FILE, new_portfolio)
    print(f"✅ 已移除 {code} {removed[0].get('name', '')}")
    return True


def clear_portfolio():
    """清空持仓"""
    save_json(PORTFOLIO_FILE, [])
    print("✅ 已清空所有持仓")


def show_portfolio():
    """显示持仓"""
    portfolio = load_json(PORTFOLIO_FILE)
    if not portfolio:
        print("📋 当前无持仓")
        return portfolio

    print(f"\n📋 当前持仓（共{len(portfolio)}只）：")
    print("-" * 70)
    print(f"{'代码':<8} {'名称':<8} {'买入价':<10} {'买入日期':<12} {'备注'}")
    print("-" * 70)
    for pos in portfolio:
        print(f"{pos.get('code', ''):<8} {pos.get('name', ''):<8} "
              f"{pos.get('buy_price', 0):<10.2f} {pos.get('buy_date', ''):<12} "
              f"{pos.get('notes', '')}")
    print("-" * 70)
    return portfolio


# ============ 自选股管理 ============

def get_watchlist():
    """获取自选股"""
    return load_json(WATCHLIST_FILE)


def add_watchlist(code, name="", reason=""):
    """添加自选股"""
    watchlist = load_json(WATCHLIST_FILE)

    for item in watchlist:
        if item.get("code") == code:
            print(f"⚠️ {code} 已在自选中")
            return False

    watchlist.append({
        "code": code,
        "name": name,
        "reason": reason,
        "added_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    save_json(WATCHLIST_FILE, watchlist)
    print(f"✅ 已添加 {code} {name} 到自选")
    return True


def remove_watchlist(code):
    """移除自选股"""
    watchlist = load_json(WATCHLIST_FILE)
    new_list = [w for w in watchlist if w.get("code") != code]

    if len(new_list) == len(watchlist):
        print(f"⚠️ {code} 不在自选中")
        return False

    save_json(WATCHLIST_FILE, new_list)
    print(f"✅ 已从自选移除 {code}")
    return True


def show_watchlist():
    """显示自选股"""
    watchlist = load_json(WATCHLIST_FILE)
    if not watchlist:
        print("📋 当前无自选股")
        return watchlist

    print(f"\n📋 自选股（共{len(watchlist)}只）：")
    print("-" * 60)
    for item in watchlist:
        print(f"  {item.get('code', '')} {item.get('name', '')} - {item.get('reason', '')}")
    print("-" * 60)
    return watchlist
