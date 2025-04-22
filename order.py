import streamlit as st
import requests
import time
import hmac
import hashlib
import pandas as pd
import urllib.parse
from datetime import datetime

BINANCE_FUTURES_API_URL = "https://fapi.binance.com"

def get_timestamp():
    return int(time.time() * 1000)

def sign_request(params, secret_key):
    query_string = urllib.parse.urlencode(params)
    return hmac.new(secret_key.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()

def get_headers(api_key):
    return {'X-MBX-APIKEY': api_key}

def signed_get(endpoint, api_key, secret_key, extra_params=None):
    params = {'timestamp': get_timestamp()}
    if extra_params:
        params.update(extra_params)
    params['signature'] = sign_request(params, secret_key)
    url = f"{BINANCE_FUTURES_API_URL}{endpoint}?{urllib.parse.urlencode(params)}"
    response = requests.get(url, headers=get_headers(api_key))
    try:
        return response.json()
    except:
        return {"msg": "无法解析响应", "raw": response.text}

def get_account_info(api_key, secret_key):
    return signed_get("/fapi/v2/account", api_key, secret_key)

def get_positions(api_key, secret_key):
    return signed_get("/fapi/v2/positionRisk", api_key, secret_key)

def get_open_orders(api_key, secret_key):
    return signed_get("/fapi/v1/openOrders", api_key, secret_key)

def get_position_history(api_key, secret_key):
    return signed_get("/fapi/v1/userTrades", api_key, secret_key, extra_params={"limit": 50})

def paginated_table(df, label, page_size=10):
    total = len(df)
    if total <= page_size:
        st.dataframe(df, use_container_width=True)
    else:
        pages = (total - 1) // page_size + 1
        page_key = f"{label}_page"
        page = st.session_state.get(page_key, 1)

        start = (page - 1) * page_size
        end = start + page_size
        st.dataframe(df.iloc[start:end], use_container_width=True)

        new_page = st.selectbox(
            f"页码选择 - {label}",
            range(1, pages + 1),
            index=page - 1,
            key=f"{label}_selector"
        )
        st.session_state[page_key] = new_page

# Streamlit UI
st.set_page_config(page_title="Binance 合约监控", layout="wide")
st.title("📊 Binance USDT 合约账户监控")

with st.sidebar:
    st.header("🔐 API 配置")
    api_key = st.text_input("API Key", type="password")
    api_secret = st.text_input("Secret Key", type="password")
    refresh_interval = st.number_input("刷新间隔（秒）", min_value=10, max_value=300, value=30, step=10)

if api_key and api_secret:
    placeholder = st.empty()

    while True:
        with placeholder.container():
            try:
                account_info = get_account_info(api_key, api_secret)
                positions = get_positions(api_key, api_secret)
                open_orders = get_open_orders(api_key, api_secret)
                trade_history = get_position_history(api_key, api_secret)

                if 'totalWalletBalance' not in account_info:
                    st.error(f"账户信息错误: {account_info.get('msg', account_info)}")
                    break

                total_wallet_balance = float(account_info['totalWalletBalance'])
                total_unrealized_profit = float(account_info['totalUnrealizedProfit'])
                margin_balance = float(account_info['totalMarginBalance'])

                st.markdown("### 💼 当前账户汇总")
                col1, col2, col3 = st.columns(3)
                col1.metric("钱包余额", f"{total_wallet_balance:.2f} USDT")
                col2.metric("未实现盈亏", f"{total_unrealized_profit:.2f} USDT")
                col3.metric("保证金余额", f"{margin_balance:.2f} USDT")

                st.markdown("### 📈 当前持仓")
                active_positions = [p for p in positions if float(p['positionAmt']) != 0]
                if active_positions:
                    df_pos = pd.DataFrame(active_positions)
                    df_pos = df_pos[[
                        'symbol', 'positionAmt', 'entryPrice', 'markPrice', 'unRealizedProfit', 'leverage', 'marginType'
                    ]]
                    df_pos.columns = ['交易对', '持仓数量', '开仓均价', '标记价格', '未实现盈亏', '杠杆', '保证金类型']
                    df_pos = df_pos.astype({
                        '持仓数量': float,
                        '开仓均价': float,
                        '标记价格': float,
                        '未实现盈亏': float,
                        '杠杆': int
                    })
                    paginated_table(df_pos, label="当前持仓")
                else:
                    st.info("无当前持仓")

                st.markdown("### 📋 当前委托订单（含中文触发条件）")
                if isinstance(open_orders, list) and open_orders:
                    processed_orders = []
                    for order in open_orders:
                        order_type = order.get('type', '')
                        trigger_price = order.get('triggerPrice', '')
                        working_type = order.get('workingType', '')
                        side = order.get('side', '')
                        trigger_condition = "-"

                        try:
                            tp = float(trigger_price)
                            if tp > 0:
                                price_cmp = "-"
                                if order_type in ['TAKE_PROFIT_MARKET', 'TAKE_PROFIT']:
                                    price_cmp = ">=" if side == 'SELL' else "<="
                                elif order_type in ['STOP_MARKET', 'STOP']:
                                    price_cmp = "<=" if side == 'SELL' else ">="
                                trigger_label = "标记价格" if working_type == "MARK_PRICE" else "最新价格"
                                trigger_condition = f"{trigger_label} {price_cmp} {tp:.4f}"
                        except:
                            pass

                        type_map = {
                            "STOP_MARKET": "市价止损",
                            "TAKE_PROFIT_MARKET": "市价止盈",
                            "STOP": "限价止损",
                            "TAKE_PROFIT": "限价止盈",
                            "LIMIT": "限价委托",
                            "MARKET": "市价委托"
                        }

                        processed_orders.append({
                            '交易对': order.get('symbol', ''),
                            '方向': order.get('side', ''),
                            '数量': order.get('origQty', ''),
                            '价格': order.get('price', ''),
                            '类型': type_map.get(order_type, order_type),
                            '状态': order.get('status', ''),
                            '触发条件': trigger_condition,
                            '下单时间': datetime.fromtimestamp(order.get('time', 0) / 1000).strftime('%Y-%m-%d %H:%M:%S')
                        })

                    df_orders = pd.DataFrame(processed_orders)
                    paginated_table(df_orders, label="当前委托")
                else:
                    st.info("无当前委托")

                st.markdown("### 🕒 最近成交记录（仓位历史）")
                if isinstance(trade_history, list) and trade_history:
                    df_trades = pd.DataFrame(trade_history)
                    df_trades = df_trades[['symbol', 'side', 'qty', 'price', 'realizedPnl', 'time']]
                    df_trades['time'] = pd.to_datetime(df_trades['time'], unit='ms')
                    df_trades.columns = ['交易对', '方向', '数量', '价格', '已实现盈亏', '时间']
                    paginated_table(df_trades, label="成交记录")
                else:
                    st.info("无成交记录")

                st.markdown(f"⏱ 最后刷新：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            except Exception as e:
                st.error(f"发生错误：{e}")
                break

        time.sleep(refresh_interval)
else:
    st.warning("请在左侧输入 API Key 和 Secret Key 后开始")
