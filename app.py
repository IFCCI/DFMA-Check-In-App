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
import google.generativeai as genai
import random

# ==========================================
# ⚙️ 配置与初始化
# ==========================================

st.set_page_config(page_title="DFMA Check-in", page_icon="✅", layout="wide")

# 获取 API Keys
try:
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
        HAS_AI = True
    else:
        HAS_AI = False
except:
    HAS_AI = False

# 文件路径配置
SESSION_FILE = "sessions.json"
BACKUP_FILE = "local_backup_logs.csv"     # 签到记录备份 (核心数据库)
LOCAL_NAMELIST = "local_namelist.csv"     # 名单备份
LOGO_FILE = "logo.png"
ADMIN_PASSWORD = "admin" 
APP_URL = "https://dfma-checkin-app-2026.streamlit.app" # 你的新网址

# ==========================================
# 🛠️ 核心功能函数
# ==========================================

# --- A. Session 管理 ---
def load_sessions():
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, 'r') as f:
            return json.load(f)
    return []

def save_sessions(sessions):
    with open(SESSION_FILE, 'w') as f:
        json.dump(sessions, f)

# --- B. 数据读取 ---
conn = st.connection("gsheets", type=GSheetsConnection)

@st.cache_data(ttl=600)
def get_participants_data():
    try:
        # 尝试从 Google 读取
        df = conn.read(worksheet="Participants", usecols=[0, 1, 2])
        # 规范化列名
        if len(df.columns) >= 3:
            df.columns = ['Name', 'Email', 'Category']
        elif len(df.columns) == 2:
            df.columns = ['Name', 'Email']
            df['Category'] = 'Pre-registered'
        else:
            df.columns = ['Name']
            df['Email'] = '-'
            df['Category'] = 'Pre-registered'
        return df.dropna(subset=['Name']).astype(str)
    except Exception:
        # 失败则读取本地上传的 CSV
        if os.path.exists(LOCAL_NAMELIST):
            try:
                df = pd.read_csv(LOCAL_NAMELIST)
                # 简单的列名修正
                if 'Name' not in df.columns: df.rename(columns={df.columns[0]: 'Name'}, inplace=True)
                if 'Email' not in df.columns: df['Email'] = '-'
                if 'Category' not in df.columns: df['Category'] = 'Uploaded'
                return df.astype(str)
            except:
                pass
        return pd.DataFrame(columns=['Name', 'Email', 'Category'])

def get_logs_data():
    # 读取日志：优先本地，因为本地是最全的
    if os.path.exists(BACKUP_FILE):
        return pd.read_csv(BACKUP_FILE)
    try:
        return conn.read(worksheet="Logs", ttl=0)
    except:
        return pd.DataFrame()

# --- C. AI ---
def ai_generate_welcome(name, session_name):
    if not HAS_AI: return f"Welcome {name}! Enjoy the class."
    try:
        model = genai.GenerativeModel('gemini-2.5-flash-preview-09-2025')
        prompt = f"Write a welcoming sentence for student {name} at '{session_name}' with a very short financial fact."
        response = model.generate_content(prompt)
        return response.text
    except:
        return f"Welcome {name}!"

# --- D. 写入逻辑 (关键修改) ---
def write_log(session_data, name, user_type, email="-", phone="-"):
    # 1. 时间处理 (KL Time)
    kl_time = datetime.utcnow() + timedelta(hours=8)
    timestamp_str = kl_time.strftime("%Y-%m-%d %H:%M:%S")
    
    # 2. 状态判断 (Status Logic Fix)
    status = "Unknown"
    try:
        start_str = f"{session_data['date']} {session_data['start']}"
        session_start = datetime.strptime(start_str, "%Y-%m-%d %H:%M")
        
        # 解析 Duration
        dur_str = str(session_data.get('duration', '1hr'))
        if 'hr' in dur_str:
            mins = int(float(dur_str.replace('hr','')) * 60)
        else:
            mins = int(dur_str.replace('m',''))
            
        # 比较时间 (当前时间 vs 开始时间 + 缓冲)
        late_threshold = session_start + timedelta(minutes=mins)
        # 注意：这里做简单的日期比较，假设是当天
        # 为了更准确，我们只比较时间部分，或者假设 event 就在当天
        # 这里使用完整 datetime 比较
        is_late = kl_time > late_threshold
        status = "Late" if is_late else "On-time"
    except Exception as e:
        print(f"Status Calc Error: {e}")
        status = "On-time" # 默认值，避免 Unknown

    new_data = pd.DataFrame([{
        "Timestamp": timestamp_str,
        "Session": session_data['name'],
        "Name": name,
        "Type": user_type,
        "Status": status,
        "Email": email,
        "Phone": phone
    }])

    # 3. 永远先写入本地 (极速)
    if not os.path.exists(BACKUP_FILE):
        new_data.to_csv(BACKUP_FILE, index=False)
    else:
        new_data.to_csv(BACKUP_FILE, mode='a', header=False, index=False)

    # 4. 检查是否开启“高峰模式”
    if st.session_state.get('high_traffic_mode', False):
        return True, status # 直接返回，不连 Google

    # 5. 如果不是高峰模式，尝试同步 Google
    try:
        existing_data = conn.read(worksheet="Logs", ttl=0)
        updated_df = pd.concat([existing_data, new_data], ignore_index=True)
        conn.update(worksheet="Logs", data=updated_df)
    except:
        pass # Google 失败也没事，本地已经存了

    return True, status

# --- E. 批量同步函数 ---
def sync_local_to_cloud():
    if not os.path.exists(BACKUP_FILE):
        return "No local data to sync."
    
    try:
        local_df = pd.read_csv(BACKUP_FILE)
        # 读取云端
        cloud_df = conn.read(worksheet="Logs", ttl=0)
        
        # 合并去重 (简单逻辑：根据 Timestamp 和 Name)
        combined_df = pd.concat([cloud_df, local_df]).drop_duplicates(subset=['Timestamp', 'Name', 'Session'], keep='last')
        
        conn.update(worksheet="Logs", data=combined_df)
        return f"✅ Synced {len(local_df)} records to Cloud successfully!"
    except Exception as e:
        return f"❌ Sync failed: {e}"

# ==========================================
# 🖥️ 页面逻辑
# ==========================================

if 'page' not in st.session_state: st.session_state.page = 'HOME'
if 'current_user' not in st.session_state: st.session_state.current_user = None
if 'welcome_msg' not in st.session_state: st.session_state.welcome_msg = ""
# 默认开启高峰模式，防止崩坏
if 'high_traffic_mode' not in st.session_state: st.session_state.high_traffic_mode = True 

sessions = load_sessions()
active_sessions = [s for s in sessions if s.get('active', True)]

# --- 1. 侧边栏：Admin 后台 ---
with st.sidebar:
    if os.path.exists(LOGO_FILE):
        st.image(LOGO_FILE, use_container_width=True)
    
    st.title("🔐 Admin Panel")
    
    # 高峰模式开关 (全局控制)
    st.markdown("### 🚦 Traffic Control")
    mode = st.toggle("High Traffic Mode (Local Only)", value=st.session_state.high_traffic_mode)
    st.session_state.high_traffic_mode = mode
    if mode:
        st.caption("✅ FAST: Data saves to local file only. Sync later.")
    else:
        st.caption("⚠️ SLOW: Syncs to Google instantly. May crash if too many users.")

    st.divider()
    
    pwd = st.text_input("Admin Password", type="password")
    
    if pwd == ADMIN_PASSWORD:
        st.success("Unlocked")
        
        tab_create, tab_manage, tab_sync = st.tabs(["Create", "Manage", "Sync/Data"])
        
        with tab_create:
            st.subheader("New Session")
            sess_name = st.text_input("Session Name", placeholder="e.g. DFMA Module 1")
            c1, c2 = st.columns(2)
            sess_date = c1.date_input("Date")
            sess_time = c2.time_input("Start Time")
            sess_dur = st.selectbox("Late Buffer", ["15m", "30m", "45m", "1hr", "2hr"])
            
            if st.button("Create Session"):
                if sess_name:
                    new_code = str(random.randint(100000, 999999))
                    new_sess = {
                        "id": int(time.time()),
                        "name": sess_name,
                        "code": new_code,
                        "date": str(sess_date),
                        "start": str(sess_time),
                        "duration": sess_dur,
                        "active": True
                    }
                    sessions.append(new_sess)
                    save_sessions(sessions)
                    st.success(f"Created! Code: {new_code}")
                    time.sleep(1)
                    st.rerun()

        with tab_manage:
            for s in active_sessions:
                with st.expander(f"{s['name']} ({s['code']})"):
                    c1, c2 = st.columns(2)
                    if c1.button("📽️ Project", key=f"p_{s['id']}"):
                        st.session_state.project_session = s
                        st.session_state.page = 'PROJECTION'
                        st.rerun()
                    if c2.button("🗑️ Delete", key=f"d_{s['id']}"):
                        sessions.remove(s)
                        save_sessions(sessions)
                        st.rerun()

        with tab_sync:
            st.subheader("☁️ Cloud Sync")
            st.info("After the event, click below to push local data to Google Sheets.")
            if st.button("Start Sync Process"):
                with st.spinner("Syncing... don't close window..."):
                    res = sync_local_to_cloud()
                    st.write(res)
            
            st.divider()
            st.subheader("📂 Local Backup")
            if os.path.exists(BACKUP_FILE):
                with open(BACKUP_FILE, "rb") as f:
                    st.download_button("📥 Download All Logs", f, "backup_logs.csv")
            
            # 导入名单
            st.subheader("📥 Import Namelist")
            uploaded_file = st.file_uploader("Upload CSV/Excel", type=['csv', 'xlsx'])
            if uploaded_file:
                if uploaded_file.name.endswith('.csv'):
                    df_up = pd.read_csv(uploaded_file)
                else:
                    df_up = pd.read_excel(uploaded_file)
                df_up.to_csv(LOCAL_NAMELIST, index=False)
                st.success(f"Imported {len(df_up)} names locally!")

# --- 2. 页面路由 ---

# A. 投屏模式
if st.session_state.page == 'PROJECTION':
    s = st.session_state.get('project_session')
    c1, c2 = st.columns([8,1])
    if c2.button("Exit"):
        st.session_state.page = 'HOME'
        st.rerun()
        
    if s:
        if os.path.exists(LOGO_FILE):
            col_l, col_m, col_r = st.columns([1, 2, 1])
            with col_m: st.image(LOGO_FILE, use_container_width=True)

        st.markdown(f"<h1 style='text-align: center; color: #1E3A8A; font-size: 50px;'>{s['name']}</h1>", unsafe_allow_html=True)
        
        col_left, col_right = st.columns([1.2, 1])
        with col_left:
            st.markdown("### 📲 Step 1: Scan QR")
            qr = qrcode.make(APP_URL)
            img_bytes = io.BytesIO()
            qr.save(img_bytes, format='PNG')
            st.image(img_bytes, width=350)
            
            st.markdown("### 🔢 Step 2: Enter Code")
            st.markdown(f"<h1 style='font-size: 80px; color: #1E40AF; margin: 0;'>{s['code']}</h1>", unsafe_allow_html=True)
            st.caption(f"Late Threshold: {s['duration']}")

        with col_right:
            logs = get_logs_data() # 读取本地或云端
            if not logs.empty and 'Session' in logs.columns:
                session_logs = logs[logs['Session'] == s['name']]
                st.metric("Total Checked-in", len(session_logs))
                
                st.markdown("### 🟢 Live Feed")
                recent = session_logs.sort_values("Timestamp", ascending=False).head(8)
                for _, row in recent.iterrows():
                    name = str(row['Name'])
                    masked = name[:2] + "***" + name[-2:] if len(name) > 4 else name
                    t_str = row['Timestamp'].split(' ')[1] # HH:MM:SS
                    st.markdown(f"**{masked}** <span style='float:right; color:gray'>{t_str}</span>", unsafe_allow_html=True)
                    st.markdown("---")
            else:
                st.info("Waiting for first check-in...")
        
        time.sleep(5)
        st.rerun()

# B. 学生签到模式
elif st.session_state.page == 'HOME':
    if os.path.exists(LOGO_FILE):
        c1, c2, c3 = st.columns([1, 2, 1])
        with c2: st.image(LOGO_FILE, use_container_width=True)
    else:
        st.title("🎓 DFMA Check-in")
    
    code = st.text_input("Enter 6-Digit Code", max_chars=6).strip()
    
    target_session = next((s for s in active_sessions if s['code'] == code), None)
    
    if target_session:
        st.success(f"✅ Class: {target_session['name']}")
        
        # 1. 过滤搜索 (解决手机键盘不弹出的问题)
        df_participants = get_participants_data()
        all_names = sorted(df_participants['Name'].unique().tolist()) if not df_participants.empty else []
        
        # 增加一个文本框来过滤，因为 selectbox 在手机上选项太多会卡
        filter_text = st.text_input("🔍 Filter Name (Type part of your name)", "")
        
        if filter_text:
            filtered_names = [n for n in all_names if filter_text.lower() in n.lower()]
        else:
            filtered_names = all_names[:50] # 默认只显示前50个，防止卡顿，迫使用户输入
            if len(all_names) > 50:
                filtered_names.append("... (Type to search)")

        selected_name = st.selectbox("Select Your Name", [""] + filtered_names)
        
        if selected_name and selected_name != "... (Type to search)":
            if st.button("Confirm Check-in", type="primary", use_container_width=True):
                # 获取信息
                try:
                    row = df_participants[df_participants['Name'] == selected_name].iloc[0]
                    cat = row['Category']
                    email = row['Email']
                except:
                    cat = "Pre-reg"
                    email = "-"
                
                success, status = write_log(target_session, selected_name, cat, email=email)
                
                # 设置成功状态
                st.session_state.current_user = {
                    "name": selected_name, 
                    "status": status, 
                    "session": target_session['name']
                }
                
                # 生成 AI 欢迎语 (异步感)
                with st.spinner("Success! Generating pass..."):
                    msg = ai_generate_welcome(selected_name, target_session['name'])
                    st.session_state.welcome_msg = msg
                
                st.session_state.page = 'SUCCESS'
                st.rerun()
        
        st.divider()
        # 显眼的 Walk-in 入口
        st.warning("⚠️ Name not in list?")
        if st.button("Click here to Register (Walk-in)", type="secondary", use_container_width=True):
            st.session_state.show_walkin = True

        if st.session_state.get('show_walkin', False):
            with st.container(border=True):
                st.markdown("### 📝 Walk-in Registration")
                wi_name = st.text_input("Full Name (as per IC)")
                wi_email = st.text_input("Email")
                wi_phone = st.text_input("Phone Number")
                
                if st.button("Submit Registration", type="primary"):
                    if wi_name and wi_email:
                        success, status = write_log(target_session, wi_name, "Walk-in", wi_email, wi_phone)
                        
                        st.session_state.current_user = {
                            "name": wi_name, 
                            "status": status, 
                            "session": target_session['name']
                        }
                        msg = ai_generate_welcome(wi_name, target_session['name'])
                        st.session_state.welcome_msg = msg
                        st.session_state.page = 'SUCCESS'
                        st.session_state.show_walkin = False
                        st.rerun()
                    else:
                        st.error("Name and Email are required!")

# C. 成功页
elif st.session_state.page == 'SUCCESS':
    user = st.session_state.current_user
    st.balloons()
    
    # 状态颜色
    status_color = "#166534" if user['status'] == 'On-time' else "#CA8A04"
    status_bg = "#F0FDF4" if user['status'] == 'On-time' else "#FEFCE8"
    status_text = "Check-in Successful!" if user['status'] == 'On-time' else "Check-in Successful (Late)"

    st.markdown(f"""
    <div style="text-align: center; padding: 30px; background-color: {status_bg}; border-radius: 20px; border: 2px solid {status_color}; margin-bottom: 20px;">
        <h1 style="color: {status_color}; font-size: 60px; margin:0;">✅</h1>
        <h2 style="color: {status_color};">{status_text}</h2>
        <h3 style="font-size: 24px; color: #1F2937;">{user['name']}</h3>
        <p style="color: #6B7280; font-size: 16px;">{user['session']}</p>
        <p style="font-weight: bold; color: {status_color}; font-size: 18px;">Status: {user['status']}</p>
        <hr style="border-top: 1px dashed #CBD5E1;">
        <p style="font-style: italic; color: #4338CA; font-size: 16px;">✨ {st.session_state.welcome_msg}</p>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("Done (Back to Home)", use_container_width=True):
        st.session_state.page = 'HOME'
        st.rerun()
