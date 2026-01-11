import os
import time
import streamlit as st
import google.generativeai as genai
import yfinance as yf
import pandas as pd

# Try to import akshare, but don't crash the whole app if it's missing
ak = None
ak_import_error = None
try:
    import akshare as ak  # type: ignore
except Exception as e:
    ak = None
    ak_import_error = e

# ⚠️ 1. 强制走本地代理 (解决国内连接 Google 的问题)
# 请确保端口 7890 与你的 VPN 软件设置一致
#os.environ["HTTP_PROXY"] = "http://127.0.0.1:7890"
#os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7890"

# === 核心数据引擎 (整合版) ===
@st.cache_data(ttl=3600)
def get_global_financial_data(market, symbol):
    """
    全能数据获取函数：支持 A股(AkShare) 和 美/港/日股(YFinance)
    """
    context = ""
    try:
        # --- A股逻辑 (AkShare) ---
        if market == "CN":
            # If akshare wasn't imported, return a friendly error explaining how to fix it
            if ak is None:
                return (
                    "❌ A股数据接口未能导入 (akshare 未安装或导入失败)。\n"
                    f"导入错误: {ak_import_error}\n"
                    "解决方法: 在运行环境中执行 `pip install akshare`，然后重启应用。\n"
                    "如果你使用 requirements.txt / Docker，请将 akshare 添加到依赖并重建镜像。"
                )

            try:
                # 1. 实时行情
                stock_spot = ak.stock_zh_a_spot_em()
                target = stock_spot[stock_spot['代码'].astype(str) == str(symbol)]
                if target.empty:
                    return f"❌ 错误：未找到A股代码 {symbol}。请检查是否输入正确（如 600519）。"

                row = target.iloc[0]
                # Use safe access (Series.get may be used; use str() to avoid errors)
                name = row.get('名称', 'N/A') if hasattr(row, 'get') else row.get('名称', 'N/A')
                latest_price = row.get('最新价', 'N/A')
                pct_chg = row.get('涨跌幅', 'N/A')
                pe_dynamic = row.get('市盈率-动态', 'N/A')
                market_cap = row.get('总市值', 'N/A')

                context += (
                    f"【实时行情】\n名称：{name}\n价格：{latest_price}\n涨跌幅：{pct_chg}%\n"
                    f"PE(动)：{pe_dynamic}\n市值：{market_cap}\n"
                )

                # 2. 财务指标 (简要提示)
                context += "【财务概况】\n(注：A股详细财务数据调用耗时较长，此处仅提供行情驱动分析)\n"

            except Exception as e:
                return f"A股数据接口报错: {e}"

        # --- 全球市场逻辑 (YFinance) ---
        else:
            # 自动补全后缀
            yf_symbol = symbol
            if market == "HK" and not symbol.endswith(".HK"):
                yf_symbol = f"{symbol}.HK"
            elif market == "JP" and not symbol.endswith(".T"):
                yf_symbol = f"{symbol}.T"

            ticker = yf.Ticker(yf_symbol)
            # ticker.info can raise or return an empty dict for some symbols
            try:
                info = ticker.info or {}
            except Exception:
                info = {}

            # 检查数据是否有效
            current_price = info.get('currentPrice') or info.get('regularMarketPrice')
            if not current_price:
                 return f"❌ 错误：未找到代码 {yf_symbol} 的数据。请检查代码是否正确（例如日股需确认是否退市或代码变更）。"

            # 提取关键信息
            currency = info.get('currency', 'USD')
            long_name = info.get('longName', symbol)

            context += f"【Basic Info】\nName: {long_name}\nPrice: {current_price} {currency}\n"
            context += f"Market Cap: {info.get('marketCap', 'N/A')}\n"
            context += f"Trailing PE: {info.get('trailingPE', 'N/A')}\n"
            context += f"Forward PE: {info.get('forwardPE', 'N/A')}\n"
            context += f"PB Ratio: {info.get('priceToBook', 'N/A')}\n"
            try:
                roe = info.get('returnOnEquity', 0)
                context += f"ROE: {roe*100:.2f}%\n"
            except Exception:
                context += f"ROE: {info.get('returnOnEquity', 'N/A')}\n"
            try:
                rev_growth = info.get('revenueGrowth', 0)
                context += f"Revenue Growth: {rev_growth*100:.2f}%\n"
            except Exception:
                context += f"Revenue Growth: {info.get('revenueGrowth', 'N/A')}\n"
            context += f"52 Week High: {info.get('fiftyTwoWeekHigh')}\n"
            context += f"Business Summary: {info.get('longBusinessSummary', 'N/A')[:500]}...\n"

    except Exception as e:
        return f"数据获取发生未知错误: {str(e)}"

    return context

# ============================

# 2. 页面配置
st.set_page_config(page_title="Global AI Stock Analyst", page_icon="🌏", layout="centered")

# -------------------------
# 应用入口认证：简单密码校验
# 密码为：zhizunbao
# 认证失败将阻止后续页面渲染
# -------------------------
password_input = st.sidebar.text_input("请输入访问密码 (Password)", type="password", help="请输入访问应用的密码")
if password_input != "zhizunbao":
    if password_input:
        st.sidebar.error("密码错误。若忘记密码，请联系管理员。")
    else:
        st.sidebar.info("请输入密码以访问应用。")
    st.stop()

# 3. 侧边栏配置
with st.sidebar:
    st.header("⚙️ 设置")

    default_key = "AIzaSyAzgQk7lEfNcsRoCBxRRbjbQR4remrFztM"
    api_key = "AIzaSyAzgQk7lEfNcsRoCBxRRbjbQR4remrFztM" #st.text_input("Gemini API Key", value=default_key, type="password")

    st.divider()
    st.success("🤖 当前模型：gemini-2.5-flash")
    model_name = "gemini-2.5-flash"

    st.divider()
    st.markdown("""
    **代码输入指南：**
    * 🇺🇸 **美股**：直接输代码 (如 `AAPL`, `NVDA`)
    * 🇭🇰 **港股**：输数字 (如 `9988`, `0700`)
    * 🇯🇵 **日股**：输数字 (如 `7203`, `8058`)
    * 🇨🇳 **A股**：输数字 (如 `600519`)
    """)

    # -------------------------
    # 搜索历史（存储过去搜索过的股票）
    # 使用 st.session_state 在当前会话内保存历史，可选提供清除功能
    # -------------------------
    if 'search_history' not in st.session_state:
        st.session_state['search_history'] = []

    # 显示历史（最近的放在前面），并支持点击快速填充输入框
    history_display = list(reversed(st.session_state['search_history']))
    history_options = [""] + history_display  # 空字符串作为占位
    selected_history = st.selectbox("搜索历史（点击以填充）", options=history_options, index=0)

    if st.button("清除搜索历史"):
        st.session_state['search_history'] = []
        st.experimental_rerun()

# 4. 主界面
st.title("🌏 全球股市 AI 研报系统")
st.caption("支持：🇺🇸 美股 (Nasdaq/NYSE) | 🇭🇰 港股 | 🇯🇵 日股 | 🇨🇳 A股")

# 市场选择逻辑优化
col1, col2 = st.columns([1, 2])
with col1:
    market_label = st.selectbox(
        "选择市场",
        [
            "🇺🇸 美股 (US)",
            "🇭🇰 港股 (HK)",
            "🇯🇵 日股 (JP)",
            "🇨🇳 A股 (CN)"
        ],
        index=0
    )
    # 提取简单的市场代码 (US, HK, JP, CN)
    market_code = market_label.split("(")[1].split(")")[0]

with col2:
    # 根据市场给出不同的默认值建议
    if market_code == "US":
        def_val = "NVDA"
    elif market_code == "HK":
        def_val = "9988"
    elif market_code == "JP":
        def_val = "7203" # 丰田
    else:
        def_val = "600519" # 茅台

    # 如果用户从历史中选择了某个股票，则优先使用选中的历史项填充输入框
    prefill = selected_history if selected_history else def_val

    symbol = st.text_input("输入股票代码", value=prefill)

# 5. Prompt 策略 (增强了对不同市场的适应性)
SYSTEM_PROMPT = """
你是一位精通全球资本市场的首席分析师。请针对用户提供的股票，��合其所在市场的特性生成逻辑清晰的个股研报，包含基本面分析、逻辑验证、��[...]
"""

# 6. 执行逻辑
if st.button("🚀 生成全球研报", use_container_width=True):
    # 在用户点击生成时，将当前搜索记录保存到历史里（去重，并限制长度）
    try:
        if 'search_history' not in st.session_state:
            st.session_state['search_history'] = []

)

