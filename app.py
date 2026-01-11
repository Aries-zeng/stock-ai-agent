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
            if ak is None:
                return (
                    "❌ A股数据接口未能导入 (akshare 未安装或导入失败)。\n"
                    f"导入错误: {ak_import_error}\n"
                    "解决方法: 在运行环境中执行 `pip install akshare`，然后重启应用。"
                )

            try:
                stock_spot = ak.stock_zh_a_spot_em()
                target = stock_spot[stock_spot['代码'].astype(str) == str(symbol)]
                if target.empty:
                    return f"❌ 错误：未找到A股代码 {symbol}。请检查是否输入正确（如 600519）。"

                row = target.iloc[0]
                name = row.get('名称', 'N/A') if hasattr(row, 'get') else row.get('名称', 'N/A')
                latest_price = row.get('最新价', 'N/A')
                pct_chg = row.get('涨跌幅', 'N/A')
                pe_dynamic = row.get('市盈率-动态', 'N/A')
                market_cap = row.get('总市值', 'N/A')

                context += (
                    f"【实时行情】\n名称：{name}\n价格：{latest_price}\n涨跌幅：{pct_chg}%\n"
                    f"PE(动)：{pe_dynamic}\n市值：{market_cap}\n"
                )
                context += "【财务概况】\n(注：A股详细财务数据调用耗时较长，此处仅提供行情驱动分析)\n"

            except Exception as e:
                return f"A股数据接口报错: {e}"

        # --- 全球市场逻辑 (YFinance) ---
        else:
            yf_symbol = symbol
            if market == "HK" and not symbol.endswith(".HK"):
                yf_symbol = f"{symbol}.HK"
            elif market == "JP" and not symbol.endswith(".T"):
                yf_symbol = f"{symbol}.T"

            ticker = yf.Ticker(yf_symbol)
            try:
                info = ticker.info or {}
            except Exception:
                info = {}

            current_price = info.get('currentPrice') or info.get('regularMarketPrice')
            if not current_price:
                 return f"❌ 错误：未找到代码 {yf_symbol} 的数据。请检查代码是否正确。"

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

# === 🔐 登录界面验证 ===
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("🔒 系统访问受限")
    st.markdown("请输入访问密码以继续：")
    password_input = st.text_input("密码", type="password")
    if st.button("登录"):
        if password_input == "   ": 
            st.session_state.logged_in = True
            st.rerun()
        else:
            st.error("❌ 密码错误，请重试。")
    st.stop()

# === 📦 初始化 Session State ===
if "history" not in st.session_state:
    st.session_state.history = []
if "current_report" not in st.session_state:
    st.session_state.current_report = "" # 用于存储当前显示的研报内容

# 3. 侧边栏配置
with st.sidebar:
    st.header("⚙️ 设置")
    api_key = st.text_input(
        "Gemini API Key", 
        type="password", 
        placeholder="在此粘贴 Key，不会明文显示",
        help="你的 Key 不会被保存。刷新页面后需要重新输入。"
    )

    st.divider()
    st.success("🤖 当前模型：gemini-2.5-flash")
    model_name = "gemini-2.5-flash"

    st.divider()
    st.markdown("""
    **代码输入指南：**
    * 🇺🇸 **美股**：直接输代码 (如 `AAPL`)
    * 🇭🇰 **港股**：输数字 (如 `9988`)
    * 🇯🇵 **日股**：输数字 (如 `7203`)
    * 🇨🇳 **A股**：输数字 (如 `600519`)
    """)
    
    # === 📜 增强版：历史搜索记录栏 ===
    st.divider()
    st.header("🕒 历史搜索记录")
    
    # 使用按钮展示历史记录，点击即可回看
    if st.session_state.history:
        # 倒序遍历，让最新的显示在最上面
        for i, item in enumerate(reversed(st.session_state.history)):
            # 兼容性处理：确保 item 是字典
            if isinstance(item, dict):
                label = item['title']
                # key 需要唯一，使用 index
                if st.button(f"📄 {label}", key=f"hist_{i}", use_container_width=True):
                    # 点击后，直接将历史内容赋值给当前显示区
                    st.session_state.current_report = item['content']
                    # 重新运行以刷新主界面显示
                    st.rerun()
    else:
        st.caption("暂无搜索记录")

# 4. 主界面
st.title("🌏 全球股市 AI 研报系统")
st.caption("支持：🇺🇸 美股 (Nasdaq/NYSE) | 🇭🇰 港股 | 🇯🇵 日股 | 🇨🇳 A股")

col1, col2 = st.columns([1, 2])
with col1:
    market_label = st.selectbox("选择市场", ["🇺🇸 美股 (US)", "🇭🇰 港股 (HK)", "🇯🇵 日股 (JP)", "🇨🇳 A股 (CN)"], index=0)
    market_code = market_label.split("(")[1].split(")")[0]

with col2:
    if market_code == "US": def_val = "NVDA"
    elif market_code == "HK": def_val = "9988"
    elif market_code == "JP": def_val = "7203"
    else: def_val = "600519"
    symbol = st.text_input("输入股票代码", value=def_val)

SYSTEM_PROMPT = """
你是一位精通全球资本市场的首席分析师。请针对用户提供的股票，合其所在市场的特性生成逻辑清晰的个股研报，包含基本面分析、逻辑验证、行业与宏观视角、催化剂观察与投资总结。
"""

# 6. 执行逻辑
if st.button("🚀 生成全球研报", use_container_width=True):
    if not api_key:
        st.error("❌ 请先在左侧侧边栏输入 Gemini API Key 才能继续！")
    else:
        start_time = time.time()
        progress_bar = st.progress(0, text="正在初始化...")
        status_box = st.status(f"🚀 正在启动 {market_code} 市场分析引擎...", expanded=True)

        progress_bar.progress(20, text=f"📡 正在连接 {market_label} 交易所接口...")
        status_box.write("📡 正在抓取实时行情与财务数据...")

        data_context = get_global_financial_data(market_code, symbol)

        if isinstance(data_context, str) and ("错误" in data_context or "报错" in data_context or "未能导入" in data_context):
            status_box.update(label="❌ 数据获取失败", state="error")
            progress_bar.empty()
            st.error(data_context)
        else:
            progress_bar.progress(50, text="🧠 数据就绪，正在请求 Gemini 进行跨市场分析...")
            status_box.write(f"🧠 数据获取成功，正在请求 Gemini {model_name}...")

            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(model_name)

                full_prompt = f"""
                {SYSTEM_PROMPT}
                ---
                【目标股票】：{market_label} - 代码 {symbol}
                【交易所实时数据】：
                {data_context}
                ---
                请开始分析：
                """

                response = model.generate_content(full_prompt)

                progress_bar.progress(100, text="✅ 生成完成！")
                end_time = time.time()
                elapsed_time = end_time - start_time
                
                # === 💾 修改：保存完整数据到历史记录 ===
                # 保存为字典结构：标题 + 内容
                history_title = f"[{market_code}] {symbol} - {time.strftime('%H:%M:%S')}"
                st.session_state.history.append({
                    "title": history_title, 
                    "content": response.text
                })
                
                # 更新当前显示内容
                st.session_state.current_report = response.text

                status_box.update(label=f"✅ 分析完成！(耗时 {elapsed_time:.2f}s)", state="complete", expanded=False)
                st.success(f"研报已生成！耗时：{elapsed_time:.2f} 秒")

                time.sleep(1)
                progress_bar.empty()

            except Exception as e:
                status_box.update(label="API 调用出错", state="error")
                progress_bar.empty()
                if "429" in str(e):
                    st.error("⚠️ 触发限流 (429)，请稍等30秒再试。")
                elif "403" in str(e):
                    st.error("🛑 API Key 无效。请检查输入的 Key 是否正确。")
                else:
                    st.error(f"Gemini 报错: {e}")

# === 🖥️ 统一展示区 (位于按钮下方) ===
# 无论是点击生成，还是点击历史记录，内容都会显示在这里
if st.session_state.current_report:
    st.divider()
    st.markdown(st.session_state.current_report)
