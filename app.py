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
# 🎨 1. PREMIUM UI 配置 (由 AI 设计)
# ==========================================

st.set_page_config(page_title="DFMA Check-in", page_icon="💎", layout="wide")

# 加载高级 CSS 样式
st.markdown("""
<style>
    /* 引入高级字体 Inter */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700&display=swap');
    
    /* 全局背景：高端金融深蓝渐变 */
    .stApp {
        background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
        font-family: 'Inter', sans-serif;
    }

    /* --- 手机端容器 (核心) --- */
    .mobile-wrapper {
        max-width: 420px;
        margin: 40px auto;
        background: rgba(255, 255, 255, 0.95);
        backdrop-filter: blur(10px);
        padding: 40px 30px;
        border-radius: 30px;
        box-shadow: 0 20px 50px rgba(30, 58, 138, 0.15);
        border: 1px solid rgba(255, 255, 255, 0.5);
    }

    /* 标题样式 */
    .app-title {
        font-size: 24px;
        font-weight: 800;
        color: #0f172a;
        text-align: center;
        letter-spacing: -0.5px;
        margin-bottom: 5px;
    }
    .app-subtitle {
        font-size: 14px;
        color: #64748b;
        text-align: center;
        margin-bottom: 30px;
    }

    /* 输入框美化 (移除 Streamlit 默认丑边框) */
    .stTextInput > div > div > input {
        background-color: #f1f5f9;
        border: 2px solid transparent;
        border-radius: 15px;
        padding: 15px;
        font-size: 16px;
        color: #334155;
        transition: all 0.3s ease;
        text-align: center;
    }
    .stTextInput > div > div > input:focus {
        background-color: #ffffff;
        border-color: #3b82f6;
        box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.1);
    }

    /* 6位验证码专用样式 */
    .code-input input {
        font-size: 36px !important;
        letter-spacing: 12px !important;
        font-weight: 700 !important;
        color: #1e3a8a !important;
        height: 70px !important;
        background: #ffffff !important;
        border: 2px solid #cbd5e1 !important;
    }

    /* 按钮重塑：渐变按钮 */
    .stButton > button {
        width: 100%;
        background: linear-gradient(90deg, #1e3a8a 0%, #2563eb 100%);
        color: white;
        border: none;
        padding: 15px;
        border-radius: 15px;
        font-weight: 600;
        font-size: 16px;
        margin-top: 10px;
        transition: transform 0.2s;
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 20px rgba(37, 99, 235, 0.2);
    }
    .stButton > button:active {
        transform: translateY(0);
    }

    /* 成功页卡片 */
    .success-card {
        text-align: center;
        padding: 40px 20px;
    }
    .status-badge {
        display: inline-block;
        padding: 8px 20px;
        border-radius: 50px;
        font-size: 14px;
        font-weight: 700;
        margin-top: 15px;
    }
    .status-ontime { background: #dcfce7; color: #166534; }
    .status-late { background: #fef9c3; color: #854d0e; }

    /* Admin 界面优化 */
    .admin-header {
        background: #1e293b;
        color: white;
        padding: 20px;
        border-radius: 15px;
        margin-bottom: 20px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    
    /* 隐藏 Streamlit 默认元素 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Live Feed 列表 */
    .feed-item {
        background: white;
        border-left: 4px solid #3b82f6;
        padding: 12px;
        margin-bottom: 8px;
        border-radius: 0 8px 8px 0;
        box-shadow: 0 2px 5px rgba(0,0,0,0.02);
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
</style>
""", unsafe_allow_html=True)

# 基础配置
SESSION_FILE = "sessions.json"
BACKUP_FILE = "local_backup_logs.csv"
LOCAL_NAMELIST = "local_namelist.csv"
LOGO_FILE = "logo.png"
ADMIN_PASSWORD = "admin"
APP_URL = "https://dfma-checkin-app-2026.streamlit.app"

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

# --- 数据读取 (IC 验证支持) ---
conn = st.connection("gsheets", type=GSheetsConnection)

@st.cache_data(ttl=600)
def get_participants_data():
    """读取 Name, Email, Category, IC"""
    try:
        df = conn.read(worksheet="Participants", usecols=[0, 1, 2, 3])
        current_cols = df.columns.tolist()
        expected_cols = ['Name', 'Email', 'Category', 'IC']
        
        rename_map = {}
        for i in range(min(len(current_cols), 4)):
            rename_map[current_cols[i]] = expected_cols[i]
        df = df.rename(columns=rename_map)
        
        for col in expected_cols:
            if col not in df.columns: df[col] = '-'
            
        # 清洗 IC (去除 .0 和空格)
        df = df.astype(str)
        if 'IC' in df.columns:
            df['IC'] = df['IC'].str.replace(r'\.0$', '', regex=True).str.strip()

        return df.dropna(subset=['Name'])
    except Exception:
        if os.path.exists(LOCAL_NAMELIST):
            try:
                df = pd.read_csv(LOCAL_NAMELIST).astype(str)
                if 'IC' in df.columns:
                    df['IC'] = df['IC'].str.replace(r'\.0$', '', regex=True).str.strip()
                return df
            except: pass
        return pd.DataFrame(columns=['Name', 'Email', 'Category', 'IC'])

def get_logs_data():
    if os.path.exists(BACKUP_FILE): return pd.read_csv(BACKUP_FILE)
    try: return conn.read(worksheet="Logs", ttl=0)
    except: return pd.DataFrame()

# --- 名字打码 ---
def mask_name_smart(name):
    name = str(name).strip()
    if len(name) <= 5: return name
    return "****" + name[-5:]

# --- 状态写入 ---
def calculate_status(session_data):
    kl_time = datetime.utcnow() + timedelta(hours=8)
    try:
        start_str = f"{session_data['date']} {session_data['start']}"
        session_start = datetime.strptime(start_str, "%Y-%m-%d %H:%M")
        dur_str = str(session_data.get('duration', '1hr'))
        if 'hr' in dur_str: mins = int(float(dur_str.replace('hr','')) * 60)
        else: mins = int(dur_str.replace('m',''))
        late_threshold = session_start + timedelta(minutes=mins)
        if kl_time > late_threshold: return "Late"
        return "On-time"
    except: return "On-time"

def write_log(session_data, name, user_type, email="-", phone="-"):
    kl_time = datetime.utcnow() + timedelta(hours=8)
    timestamp_str = kl_time.strftime("%Y-%m-%d %H:%M:%S")
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

    if not os.path.exists(BACKUP_FILE):
        new_data.to_csv(BACKUP_FILE, index=False)
    else:
        new_data.to_csv(BACKUP_FILE, mode='a', header=False, index=False)

    if st.session_state.get('high_traffic_mode', True):
        return True, status

    try:
        existing_data = conn.read(worksheet="Logs", ttl=0)
        updated_df = pd.concat([existing_data, new_data], ignore_index=True)
        conn.update(worksheet="Logs", data=updated_df)
    except: pass

    return True, status

def sync_local_to_cloud():
    if not os.path.exists(BACKUP_FILE): return "No local data."
    try:
        local = pd.read_csv(BACKUP_FILE)
        try:
            cloud = conn.read(worksheet="Logs", ttl=0)
            combined = pd.concat([cloud, local]).drop_duplicates(subset=['Timestamp', 'Name'], keep='last')
        except: combined = local
        conn.update(worksheet="Logs", data=combined)
        return f"✅ Synced {len(local)} records!"
    except Exception as e: return f"❌ Error: {e}"

# ==========================================
# 🖥️ 3. 界面渲染
# ==========================================

if 'page' not in st.session_state: st.session_state.page = 'HOME'
if 'current_user' not in st.session_state: st.session_state.current_user = None
if 'high_traffic_mode' not in st.session_state: st.session_state.high_traffic_mode = True 

sessions = load_sessions()
active_sessions = [s for s in sessions if s.get('active', True)]

# --- Admin Sidebar ---
with st.sidebar:
    st.title("🔐 Admin Panel")
    
    # 模式开关
    mode = st.toggle("🚀 High Traffic Mode", value=st.session_state.high_traffic_mode)
    st.session_state.high_traffic_mode = mode
    if mode: st.caption("✅ Local Save (Fast)")
    else: st.caption("⚠️ Cloud Sync (Slow)")
    st.divider()

    if st.text_input("Password", type="password") == ADMIN_PASSWORD:
        st.success("Unlocked")
        
        tab1, tab2 = st.tabs(["Manage", "Data"])
        
        with tab1:
            st.subheader("New Session")
            s_name = st.text_input("Session Name", placeholder="e.g. Module 1")
            c1, c2 = st.columns(2)
            s_date = c1.date_input("Date")
            s_time = c2.time_input("Start")
            s_dur = st.selectbox("Late Buffer", ["15m", "30m", "1hr"])
            
            if st.button("Create Session"):
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
                    if c_b.button("Delete", key=f"d{s['id']}"):
                        sessions.remove(s)
                        save_sessions(sessions)
                        st.rerun()

        with tab2:
            st.info("Sync local data to Google Sheets after event.")
            if st.button("☁️ Sync Now"):
                with st.spinner("Syncing..."):
                    res = sync_local_to_cloud()
                    st.write(res)
            
            if os.path.exists(BACKUP_FILE):
                with open(BACKUP_FILE, "rb") as f:
                    st.download_button("📥 Download CSV", f, "logs.csv")

# --- 页面路由 ---

# A. 投屏页面 (Project Screen - 全新设计)
if st.session_state.page == 'PROJECTION':
    s = st.session_state.get('project_session')
    
    # 顶部工具栏
    c1, c2 = st.columns([1, 10])
    if c1.button("⬅️ Exit"):
        st.session_state.page = 'HOME'
        st.rerun()
        
    if s:
        # 主布局
        st.markdown(f"""
        <div style="text-align: center; margin-bottom: 40px;">
            <h1 style="font-size: 3.5rem; color: #1e293b; margin: 0;">{s['name']}</h1>
            <p style="font-size: 1.5rem; color: #64748b;">Attendance Check-in</p>
        </div>
        """, unsafe_allow_html=True)

        col_L, col_R = st.columns([1, 1])

        with col_L:
            # 左侧：核心签到区 (Logo + QR + Code)
            st.markdown("""
            <div style="background: white; padding: 40px; border-radius: 30px; box-shadow: 0 10px 30px rgba(0,0,0,0.05); text-align: center;">
            """, unsafe_allow_html=True)
            
            # Logo
            if os.path.exists(LOGO_FILE):
                st.image(LOGO_FILE, width=120)
            
            # QR Code
            st.markdown("### 1. SCAN QR")
            qr = qrcode.make(APP_URL)
            img = io.BytesIO()
            qr.save(img, format='PNG')
            st.image(img, width=280)
            
            st.markdown("---")
            
            # Code
            st.markdown("### 2. ENTER CODE")
            st.markdown(f"<div style='font-size: 90px; font-weight: 800; color: #2563eb; letter-spacing: 5px; line-height: 1;'>{s['code']}</div>", unsafe_allow_html=True)
            st.caption(f"Late check-in after {s['duration']}")
            
            st.markdown("</div>", unsafe_allow_html=True)

        with col_R:
            # 右侧：实时数据区
            logs = get_logs_data()
            session_logs = logs[logs['Session'] == s['name']] if not logs.empty and 'Session' in logs.columns else pd.DataFrame()
            count = len(session_logs)
            
            # 总数卡片
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%); color: white; padding: 30px; border-radius: 30px; text-align: center; margin-bottom: 20px; box-shadow: 0 10px 20px rgba(30, 58, 138, 0.3);">
                <div style="font-size: 16px; opacity: 0.8; letter-spacing: 2px;">TOTAL CHECKED-IN</div>
                <div style="font-size: 72px; font-weight: 800;">{count}</div>
            </div>
            """, unsafe_allow_html=True)

            # 滚动列表
            st.markdown("### 🟢 Recent Activity")
            if not session_logs.empty:
                display_logs = session_logs.sort_values("Timestamp", ascending=False).head(8)
                for _, row in display_logs.iterrows():
                    masked_name = mask_name_smart(row['Name'])
                    time_only = row['Timestamp'].split(' ')[1][:5]
                    st.markdown(f"""
                    <div class="feed-item">
                        <span style="font-weight: 600; color: #334155; font-size: 18px;">{masked_name}</span>
                        <span style="font-family: monospace; color: #94a3b8;">{time_only}</span>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("Waiting for check-ins...")

        time.sleep(5)
        st.rerun()

# B. 手机端 (Home - 极简金融风)
elif st.session_state.page == 'HOME':
    st.markdown('<div class="mobile-wrapper">', unsafe_allow_html=True)
    
    # 顶部 Logo
    if os.path.exists(LOGO_FILE):
        c1, c2, c3 = st.columns([1, 2, 1])
        with c2: st.image(LOGO_FILE, use_container_width=True)
    
    st.markdown('<div class="app-title">DFMA Check-in</div>', unsafe_allow_html=True)
    st.markdown('<div class="app-subtitle">Secure Attendance System</div>', unsafe_allow_html=True)
    
    # 1. 验证码输入 (超大字号)
    st.markdown("<label style='font-size: 12px; color: #64748b; font-weight: 700; letter-spacing: 1px; display:block; margin-bottom:8px; text-align:center;'>ENTER 6-DIGIT CODE</label>", unsafe_allow_html=True)
    
    st.markdown('<div class="code-input">', unsafe_allow_html=True)
    code = st.text_input("code", label_visibility="collapsed", max_chars=6, placeholder="______").strip()
    st.markdown('</div>', unsafe_allow_html=True)
    
    target_session = next((s for s in active_sessions if s['code'] == code), None)
    
    if target_session:
        st.success(f"📍 {target_session['name']}")
        
        # 2. 搜索名字
        df_participants = get_participants_data()
        all_names = sorted(df_participants['Name'].unique().tolist()) if not df_participants.empty else []
        
        search_query = st.selectbox("Select Name", [""] + all_names, placeholder="Type to search...", index=0)
        
        if search_query:
            st.markdown("---")
            # 3. IC 验证
            st.markdown("<div style='text-align:center; font-weight:600; color:#334155; margin-bottom:10px;'>🔐 Verify Identity</div>", unsafe_allow_html=True)
            ic_input = st.text_input("Last 4 Digits of IC", max_chars=4, type="password", placeholder="****")
            
            if st.button("Check In Now"):
                try:
                    user_row = df_participants[df_participants['Name'] == search_query].iloc[0]
                    # 清洗数据
                    real_ic = str(user_row.get('IC', '0000')).replace('.0', '').strip()
                    
                    if len(ic_input) == 4 and real_ic.endswith(ic_input):
                        cat = user_row.get('Category', 'Unknown')
                        email = user_row.get('Email', '-')
                        success, status = write_log(target_session, search_query, cat, email=email)
                        st.session_state.current_user = {"name": search_query, "status": status, "session": target_session['name']}
                        st.session_state.page = 'SUCCESS'
                        st.rerun()
                    else:
                        st.error("❌ IC Verification Failed")
                except Exception as e:
                    st.error(f"Error: {e}")

        # Walk-in 区域
        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("Name not in list? (Walk-in)"):
            wi_name = st.text_input("Full Name")
            wi_email = st.text_input("Email")
            wi_phone = st.text_input("Phone")
            if st.button("Register Walk-in"):
                if wi_name and wi_email:
                    success, status = write_log(target_session, wi_name, "Walk-in", wi_email, wi_phone)
                    st.session_state.current_user = {"name": wi_name, "status": status, "session": target_session['name']}
                    st.session_state.page = 'SUCCESS'
                    st.rerun()
                else:
                    st.error("Missing fields")
    
    st.markdown('</div>', unsafe_allow_html=True)

# C. 成功页 (金融风 K 线图)
elif st.session_state.page == 'SUCCESS':
    user = st.session_state.current_user
    
    st.markdown('<div class="mobile-wrapper">', unsafe_allow_html=True)
    
    status_text = "ON TIME" if user['status'] == 'On-time' else "LATE"
    css_class = "status-ontime" if user['status'] == 'On-time' else "status-late"
    color = "#16a34a" if user['status'] == 'On-time' else "#ca8a04"
    
    st.markdown(f"""
    <div class="success-card">
        <!-- 动态 SVG K线图 -->
        <svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-bottom: 20px;">
            <path d="M17 3v18"/><path d="M7 3v18"/><path d="M13 8h8v8h-8z"/><path d="M3 8h8v8H3z"/>
        </svg>
        
        <h2 style="color: #0f172a; margin: 0; font-size: 26px;">Check-in Successful</h2>
        <p style="color: #64748b; font-size: 14px; margin-top: 5px;">{user['session']}</p>
        
        <div style="margin: 30px 0;">
            <h3 style="font-size: 22px; color: #1e3a8a; margin: 0; font-weight: 700;">{user['name']}</h3>
            <span class="status-badge {css_class}">{status_text}</span>
        </div>
        
        <hr style="border-top: 1px solid #e2e8f0; margin: 20px 0;">
        <p style="color: #94a3b8; font-size: 12px;">You may now enter the hall.</p>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("Done"):
        st.session_state.page = 'HOME'
        st.rerun()
        
    st.markdown('</div>', unsafe_allow_html=True)
