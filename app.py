import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, timedelta
import time
import json
import os
import qrcode
from PIL import Image
import io
import random

# ==========================================
# 🎨 1. 深度美化配置 (Custom CSS)
# ==========================================

st.set_page_config(page_title="DFMA Check-in", page_icon="📊", layout="wide")

# 加载自定义 CSS
st.markdown("""
<style>
    /* 全局字体 */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    /* --- 手机端优化 --- */
    .mobile-container {
        max-width: 400px;
        margin: 0 auto;
        background-color: #ffffff;
        padding: 25px;
        border-radius: 20px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08);
        border: 1px solid #f1f5f9;
    }
    
    /* 仿 6 格输入框 (通过增加字间距实现，比 6 个框更稳定) */
    .code-input input {
        font-size: 32px !important;
        letter-spacing: 12px !important;
        text-align: center !important;
        font-weight: 800 !important;
        color: #1e3a8a !important;
        background-color: #f8fafc;
        border: 2px solid #e2e8f0;
        border-radius: 12px;
        height: 60px;
    }
    .code-input input:focus {
        border-color: #3b82f6;
        box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.1);
    }

    /* 成功页 K线图动画容器 */
    .success-box {
        background: linear-gradient(to bottom, #f0fdf4, #ffffff);
        border: 2px solid #22c55e;
        border-radius: 20px;
        padding: 30px;
        text-align: center;
        margin-top: 20px;
    }

    /* Logo 调整 */
    .logo-small {
        width: 60px;
        display: block;
        margin-bottom: 10px;
    }

    /* --- 后台投屏优化 --- */
    .projection-card {
        background: white;
        padding: 20px;
        border-radius: 15px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
    }
    .live-feed-item {
        font-family: 'Courier New', monospace;
        padding: 8px 12px;
        border-bottom: 1px solid #f1f5f9;
        display: flex;
        justify-content: space-between;
        color: #475569;
    }
    .live-feed-item:first-child {
        background-color: #f0fdf4;
        color: #166534;
        font-weight: bold;
        border-radius: 8px;
    }
    
    /* 隐藏 Streamlit 默认元素 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Walk-in 警告框突出 */
    .walkin-box {
        border: 2px dashed #f87171;
        background-color: #fef2f2;
        padding: 15px;
        border-radius: 10px;
        margin-top: 20px;
    }
</style>
""", unsafe_allow_html=True)

# 基础配置
SESSION_FILE = "sessions.json"
BACKUP_FILE = "local_backup_logs.csv"
LOCAL_NAMELIST = "local_namelist.csv"
LOGO_FILE = "logo.png"
ADMIN_PASSWORD = "admin"
APP_URL = "https://dfma-checkin-app-2026.streamlit.app" # 您的真实网址

# ==========================================
# 🛠️ 2. 核心逻辑 (High Traffic & Logic Fixes)
# ==========================================

# --- Session 管理 ---
def load_sessions():
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, 'r') as f: return json.load(f)
    return []

def save_sessions(sessions):
    with open(SESSION_FILE, 'w') as f: json.dump(sessions, f)

# --- 数据读取 (IC 验证支持 - 修复版) ---
conn = st.connection("gsheets", type=GSheetsConnection)

@st.cache_data(ttl=600)
def get_participants_data():
    """读取 Name, Email, Category, IC (确保 Google Sheet 有这些列)"""
    try:
        # 尝试读 4 列: Name, Email, Category, IC
        df = conn.read(worksheet="Participants", usecols=[0, 1, 2, 3])
        
        # 简单的列名映射，防止 Excel 表头不一样
        current_cols = df.columns.tolist()
        expected_cols = ['Name', 'Email', 'Category', 'IC']
        
        # 暴力重命名: 无论表头叫什么，第1列就是Name，第4列就是IC
        rename_map = {}
        for i in range(min(len(current_cols), 4)):
            rename_map[current_cols[i]] = expected_cols[i]
        df = df.rename(columns=rename_map)
        
        # 补全缺失列
        for col in expected_cols:
            if col not in df.columns: df[col] = '-'
            
        # 1. 先转字符串
        df = df.astype(str)
        
        # 2. 🧼 关键修复：清洗 IC 列
        # 去除 .0 (针对数字被读成 float 的情况) 并去除前后空格
        if 'IC' in df.columns:
            df['IC'] = df['IC'].str.replace(r'\.0$', '', regex=True).str.strip()

        return df.dropna(subset=['Name'])
    except Exception:
        # 灾备：读本地
        if os.path.exists(LOCAL_NAMELIST):
            try:
                df = pd.read_csv(LOCAL_NAMELIST)
                df = df.astype(str)
                if 'IC' in df.columns:
                    df['IC'] = df['IC'].str.replace(r'\.0$', '', regex=True).str.strip()
                return df
            except: pass
        return pd.DataFrame(columns=['Name', 'Email', 'Category', 'IC'])

def get_logs_data():
    # 优先读本地 (最全)
    if os.path.exists(BACKUP_FILE): return pd.read_csv(BACKUP_FILE)
    try: return conn.read(worksheet="Logs", ttl=0)
    except: return pd.DataFrame()

# --- 名字打码逻辑 (新) ---
def mask_name_smart(name):
    """
    Yeoh Sin Ni -> ****in Ni (Hide front, show last 5 chars excluding spaces logic roughly)
    Simple approach: Show last 5 characters.
    """
    name = str(name).strip()
    if len(name) <= 5: return name # 名字太短不打码
    return "****" + name[-5:]

# --- 状态判断与写入 (Walk-in Status Fix) ---
def calculate_status(session_data):
    kl_time = datetime.utcnow() + timedelta(hours=8)
    
    try:
        start_str = f"{session_data['date']} {session_data['start']}"
        session_start = datetime.strptime(start_str, "%Y-%m-%d %H:%M")
        
        # 解析 Duration
        dur_str = str(session_data.get('duration', '1hr'))
        if 'hr' in dur_str:
            mins = int(float(dur_str.replace('hr','')) * 60)
        else:
            mins = int(dur_str.replace('m',''))
            
        late_threshold = session_start + timedelta(minutes=mins)
        
        if kl_time > late_threshold:
            return "Late"
        return "On-time"
    except:
        # 如果解析失败，默认当作 On-time (宽容模式)
        return "On-time"

def write_log(session_data, name, user_type, email="-", phone="-"):
    kl_time = datetime.utcnow() + timedelta(hours=8)
    timestamp_str = kl_time.strftime("%Y-%m-%d %H:%M:%S")
    
    # 确保 Walk-in 也能正确计算状态
    status = calculate_status(session_data)

    new_data = pd.DataFrame([{
        "Timestamp": timestamp_str,
        "Session": session_data['name'],
        "Name": name,
        "Type": user_type,
        "Status": status,
        "Email": email,
        "Phone": phone
    }])

    # 1. 极速写入本地 (High Traffic 保命)
    if not os.path.exists(BACKUP_FILE):
        new_data.to_csv(BACKUP_FILE, index=False)
    else:
        new_data.to_csv(BACKUP_FILE, mode='a', header=False, index=False)

    # 2. 检查高峰模式
    if st.session_state.get('high_traffic_mode', True):
        # 开启高峰模式：只写本地，不连 Google，速度最快
        return True, status

    # 3. 非高峰模式：尝试同步 Google
    try:
        existing_data = conn.read(worksheet="Logs", ttl=0)
        updated_df = pd.concat([existing_data, new_data], ignore_index=True)
        conn.update(worksheet="Logs", data=updated_df)
    except:
        pass # 失败也不报错，因为本地已经存了

    return True, status

def sync_local_to_cloud():
    if not os.path.exists(BACKUP_FILE): return "No local data."
    try:
        local = pd.read_csv(BACKUP_FILE)
        # 读取云端
        try:
            cloud = conn.read(worksheet="Logs", ttl=0)
            combined = pd.concat([cloud, local]).drop_duplicates(subset=['Timestamp', 'Name'], keep='last')
        except:
            combined = local # 如果云端读不到，就直接覆盖
            
        conn.update(worksheet="Logs", data=combined)
        return f"✅ Synced {len(local)} records!"
    except Exception as e: return f"❌ Error: {e}"

# ==========================================
# 🖥️ 3. 页面渲染逻辑
# ==========================================

if 'page' not in st.session_state: st.session_state.page = 'HOME'
if 'current_user' not in st.session_state: st.session_state.current_user = None
# 默认开启高峰模式 (High Traffic Mode)
if 'high_traffic_mode' not in st.session_state: st.session_state.high_traffic_mode = True 

sessions = load_sessions()
active_sessions = [s for s in sessions if s.get('active', True)]

# --- Admin Sidebar (管理后台) ---
with st.sidebar:
    if os.path.exists(LOGO_FILE):
        st.image(LOGO_FILE, width=100)
    
    st.title("🔐 Admin")
    
    # 高峰模式开关
    st.markdown("---")
    st.markdown("### 🚦 Traffic Control")
    mode = st.toggle("High Traffic Mode", value=st.session_state.high_traffic_mode, help="ON: Save locally only (Fast). OFF: Sync to Google instantly (Slower).")
    st.session_state.high_traffic_mode = mode
    if mode:
        st.success("⚡ Mode: FAST (Local Only)")
    else:
        st.warning("🐢 Mode: SLOW (Cloud Sync)")
    st.markdown("---")

    if st.text_input("Password", type="password") == ADMIN_PASSWORD:
        st.success("Unlocked")
        
        tab1, tab2 = st.tabs(["Session", "Data"])
        
        with tab1:
            st.subheader("Create Session")
            s_name = st.text_input("Name", placeholder="e.g. DFMA Module 1")
            c1, c2 = st.columns(2)
            s_date = c1.date_input("Date")
            s_time = c2.time_input("Start")
            s_dur = st.selectbox("Late Buffer", ["15m", "30m", "1hr"])
            
            if st.button("Create"):
                new_s = {
                    "id": int(time.time()),
                    "name": s_name,
                    "code": str(random.randint(100000, 999999)),
                    "date": str(s_date),
                    "start": str(s_time),
                    "duration": s_dur,
                    "active": True
                }
                sessions.append(new_s)
                save_sessions(sessions)
                st.rerun()
            
            st.markdown("### Active Sessions")
            for s in active_sessions:
                with st.container(border=True):
                    st.write(f"**{s['name']}**")
                    c_a, c_b = st.columns([2, 1])
                    if c_a.button("📽️ Project", key=f"p{s['id']}"):
                        st.session_state.project_session = s
                        st.session_state.page = 'PROJECTION'
                        st.rerun()
                    if c_b.button("Del", key=f"d{s['id']}"):
                        sessions.remove(s)
                        save_sessions(sessions)
                        st.rerun()

        with tab2:
            st.info("After event, sync local data to Google Sheets.")
            if st.button("☁️ Sync Now"):
                with st.spinner("Syncing..."):
                    res = sync_local_to_cloud()
                    st.write(res)
            
            if os.path.exists(BACKUP_FILE):
                with open(BACKUP_FILE, "rb") as f:
                    st.download_button("📥 Download Local CSV", f, "logs.csv")

# --- 页面路由 ---

# A. 投屏页面 (Project Screen - 美化版)
if st.session_state.page == 'PROJECTION':
    s = st.session_state.get('project_session')
    
    # 顶部退出栏
    c1, c2 = st.columns([1, 10])
    if c1.button("Exit"):
        st.session_state.page = 'HOME'
        st.rerun()
        
    if s:
        # 主标题区
        st.markdown(f"<h1 style='text-align: center; color: #1e3a8a; margin-bottom: 5px;'>{s['name']}</h1>", unsafe_allow_html=True)
        st.markdown(f"<p style='text-align: center; color: #64748b; font-size: 1.2rem; margin-top:0;'>Attendance Check-in</p>", unsafe_allow_html=True)
        st.markdown("---")

        # 左右分栏 (左3右2，二维码稍微小一点)
        col_L, col_R = st.columns([3, 2])

        with col_L:
            # 投屏卡片
            st.markdown("""
            <div class="projection-card">
                <div style="font-size: 20px; font-weight: bold; color: #64748b; margin-bottom: 10px;">SCAN TO CHECK-IN</div>
            """, unsafe_allow_html=True)
            
            # QR Code
            qr = qrcode.make(APP_URL)
            img = io.BytesIO()
            qr.save(img, format='PNG')
            st.image(img, width=250) # 缩小 QR
            
            st.markdown(f"""
                <div style="margin-top: 20px; font-size: 18px; font-weight: bold; color: #64748b;">CODE</div>
                <div style="font-size: 80px; font-weight: 800; color: #2563eb; line-height: 1;">{s['code']}</div>
                <div style="margin-top: 10px; color: #ef4444; font-size: 14px;">Late check-in after {s['duration']}</div>
            </div>
            """, unsafe_allow_html=True)

        with col_R:
            # 实时数据
            logs = get_logs_data()
            count = 0
            display_logs = pd.DataFrame()
            
            if not logs.empty and 'Session' in logs.columns:
                current_logs = logs[logs['Session'] == s['name']]
                count = len(current_logs)
                display_logs = current_logs.sort_values("Timestamp", ascending=False).head(10)

            # 总数展示
            st.markdown(f"""
            <div style="background: #1e3a8a; color: white; padding: 20px; border-radius: 15px; text-align: center; margin-bottom: 20px;">
                <div style="font-size: 14px; opacity: 0.8; letter-spacing: 1px;">TOTAL CHECKED-IN</div>
                <div style="font-size: 48px; font-weight: 800;">{count}</div>
            </div>
            """, unsafe_allow_html=True)

            # 滚动列表
            st.markdown("### Recent Activity")
            if not display_logs.empty:
                for _, row in display_logs.iterrows():
                    masked_name = mask_name_smart(row['Name'])
                    time_only = row['Timestamp'].split(' ')[1][:5]
                    st.markdown(f"""
                    <div class="live-feed-item">
                        <span>{masked_name}</span>
                        <span>{time_only}</span>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("Waiting for students...")

        time.sleep(5)
        st.rerun()

# B. 手机端 (Home - 优化版)
elif st.session_state.page == 'HOME':
    st.markdown('<div class="mobile-container">', unsafe_allow_html=True)
    
    # 顶部 Logo
    if os.path.exists(LOGO_FILE):
        st.image(LOGO_FILE, width=60) # 进一步缩小
    
    st.markdown("<h3 style='margin-top:0; color:#1e293b;'>DFMA Check-in</h3>", unsafe_allow_html=True)
    
    # 1. 验证码输入 (使用 Custom CSS 伪装成 6 格)
    st.markdown("<label style='font-size: 12px; color: #64748b; font-weight: 600; letter-spacing: 1px;'>ENTER 6-DIGIT CODE</label>", unsafe_allow_html=True)
    
    # 用一个输入框，但样式改成大间距
    st.markdown('<div class="code-input">', unsafe_allow_html=True)
    code = st.text_input("code", label_visibility="collapsed", max_chars=6, placeholder="______").strip()
    st.markdown('</div>', unsafe_allow_html=True)
    
    target_session = next((s for s in active_sessions if s['code'] == code), None)
    
    if target_session:
        st.success(f"📍 {target_session['name']}")
        
        # 2. 搜索名字 (优化搜索逻辑)
        df_participants = get_participants_data()
        
        # 搜索框代替 Selectbox
        all_names = sorted(df_participants['Name'].unique().tolist()) if not df_participants.empty else []
        
        # 使用 selectbox 配合 placeholder
        search_query = st.selectbox("Search Name", [""] + all_names, placeholder="Type your name...", index=0)
        
        if search_query:
            st.markdown("---")
            # 3. IC 验证 (新规则)
            st.markdown("**🔐 Identity Verification**")
            st.caption("Please enter the last 4 digits of your IC No.")
            ic_input = st.text_input("IC Last 4 Digits", max_chars=4, type="password", placeholder="e.g. 1234")
            
            if st.button("Verify & Check-in", type="primary", use_container_width=True):
                try:
                    user_row = df_participants[df_participants['Name'] == search_query].iloc[0]
                    # 获取真实 IC (确保转为字符串)
                    real_ic = str(user_row.get('IC', '0000')).strip()
                    
                    if len(ic_input) == 4 and real_ic.endswith(ic_input):
                        # 验证通过
                        cat = user_row.get('Category', 'Unknown')
                        email = user_row.get('Email', '-')
                        
                        success, status = write_log(target_session, search_query, cat, email=email)
                        
                        st.session_state.current_user = {"name": search_query, "status": status, "session": target_session['name']}
                        st.session_state.page = 'SUCCESS'
                        st.rerun()
                    else:
                        st.error("❌ IC does not match our records.")
                except Exception as e:
                    st.error(f"Verification Error: {e}")

        # Walk-in 区域 (醒目设计)
        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("🚨 Name not in list? (Walk-in)"):
            st.markdown('<div class="walkin-box">', unsafe_allow_html=True)
            wi_name = st.text_input("Full Name")
            wi_email = st.text_input("Email")
            wi_phone = st.text_input("Phone")
            
            if st.button("Register Walk-in", type="secondary", use_container_width=True):
                if wi_name and wi_email:
                    success, status = write_log(target_session, wi_name, "Walk-in", wi_email, wi_phone)
                    st.session_state.current_user = {"name": wi_name, "status": status, "session": target_session['name']}
                    st.session_state.page = 'SUCCESS'
                    st.rerun()
                else:
                    st.error("Name & Email required.")
            st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown('</div>', unsafe_allow_html=True)

# C. 成功页 (金融风)
elif st.session_state.page == 'SUCCESS':
    user = st.session_state.current_user
    
    st.markdown('<div class="mobile-container">', unsafe_allow_html=True)
    
    # 状态显示
    status_text = "On-Time" if user['status'] == 'On-time' else "Late"
    color_hex = "#16a34a" if user['status'] == 'On-time' else "#ca8a04"
    
    st.markdown(f"""
    <div class="success-box" style="border-color: {color_hex};">
        <!-- 动态 K 线图 SVG -->
        <svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="{color_hex}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-bottom: 10px;">
            <path d="M17 3v18"/><path d="M7 3v18"/><path d="M13 8h8v8h-8z"/><path d="M3 8h8v8H3z"/>
        </svg>
        <h2 style="color: #0f172a; margin: 0; font-size: 24px;">Check-in Successful</h2>
        <p style="color: #64748b; font-size: 14px;">{user['session']}</p>
        <hr style="margin: 15px 0; border-top: 1px dashed #cbd5e1;">
        <h3 style="font-size: 20px; color: #1e3a8a; margin: 0;">{user['name']}</h3>
        <br>
        <span style="background-color: {color_hex}; color: white; padding: 5px 15px; border-radius: 15px; font-size: 14px; font-weight: bold;">{status_text}</span>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("Done", use_container_width=True):
        st.session_state.page = 'HOME'
        st.rerun()
        
    st.markdown('</div>', unsafe_allow_html=True)
