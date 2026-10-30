
import json
import time
import threading
from collections import deque
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import paho.mqtt.client as mqtt
from streamlit_autorefresh import st_autorefresh

st.set_page_config(
    page_title="Smartphone Thermal Monitor",
    page_icon="📱",
    layout="wide",
    initial_sidebar_state="expanded"
)

MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPIC = "smartphone/thermal/telemetry"

if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = True

with st.sidebar:
    st.title("⚙️ Pengaturan")

    mode = st.radio(
        "Tema dashboard",
        options=["Dark", "Light"],
        index=0,
        horizontal=True,
        key="theme_selector"
    )

    st.session_state.dark_mode = mode == "Dark"

    st.divider()

    st.markdown("### 📡 Koneksi MQTT")
    st.code(MQTT_BROKER, language=None)
    st.caption(f"Port: {MQTT_PORT}")
    st.caption(f"Topic: {MQTT_TOPIC}")

    st.divider()

    st.markdown("### 🌡️ Batas Suhu")
    st.markdown("- 🟢 Idle: < 30°C")
    st.markdown("- 🟡 Ringan: 30–<37°C")
    st.markdown("- 🟠 Berat: 37–<44°C")
    st.markdown("- 🔴 Overheat: ≥ 44°C")


if st.session_state.dark_mode:
    BG_COLOR = "#0E1117"
    CARD_COLOR = "#1B2330"
    TEXT_COLOR = "#F1F5F9"
    MUTED_COLOR = "#A7B0C0"
    BORDER_COLOR = "#303B4B"
    GRID_COLOR = "#39465A"
    TICK_COLOR = "#D7DFEA"
else:
    BG_COLOR = "#F5F7FB"
    CARD_COLOR = "#FFFFFF"
    TEXT_COLOR = "#172033"
    MUTED_COLOR = "#475569"
    BORDER_COLOR = "#CBD5E1"
    GRID_COLOR = "#E2E8F0"
    TICK_COLOR = "#334155"


st.markdown(
    f"""
    <style>
    .stApp {{
        background-color: {BG_COLOR};
        color: {TEXT_COLOR};
    }}

    [data-testid="stHeader"] {{
        background-color: {BG_COLOR};
    }}

    [data-testid="stSidebar"] {{
        background-color: {CARD_COLOR};
        border-right: 1px solid {BORDER_COLOR};
    }}

    [data-testid="stMetric"] {{
        background-color: {CARD_COLOR};
        border: 1px solid {BORDER_COLOR};
        padding: 16px;
        border-radius: 12px;
    }}

    [data-testid="stMetricLabel"],
    [data-testid="stMetricValue"],
    [data-testid="stMarkdownContainer"],
    [data-testid="stCaptionContainer"] {{
        color: {TEXT_COLOR};
    }}

    h1, h2, h3, p, label {{
        color: {TEXT_COLOR};
    }}

    [data-testid="stDataFrame"] {{
        border: 1px solid {BORDER_COLOR};
        border-radius: 10px;
    }}

    div[data-testid="stAlert"] {{
        border-radius: 10px;
    }}

    </style>
    """,
    unsafe_allow_html=True
)

st_autorefresh(
    interval=2000,
    key="mqtt_refresh"
)

st.title("📱 Smartphone Thermal Monitoring")
st.caption(
    "Real-Time IoT Dashboard | ESP32 · Wokwi · MQTT"
)

@st.cache_resource
def get_shared_data():
    return {
        "history": deque(maxlen=300),
        "lock": threading.Lock(),
        "connected": False,
        "last_message": None,
        "error": None
    }


shared = get_shared_data()

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        with shared["lock"]:
            shared["connected"] = True
            shared["error"] = None

        client.subscribe(MQTT_TOPIC, qos=0)
        print(f"MQTT terhubung: {MQTT_TOPIC}")

    else:
        with shared["lock"]:
            shared["connected"] = False
            shared["error"] = (
                f"Koneksi MQTT gagal: {reason_code}"
            )


def on_disconnect(
    client,
    userdata,
    disconnect_flags,
    reason_code,
    properties
):
    with shared["lock"]:
        shared["connected"] = False


def on_message(client, userdata, msg):
    try:
        payload = json.loads(
            msg.payload.decode("utf-8")
        )

        record = {
            "time": datetime.now(),
            "soc_temperature": float(
                payload["soc_temperature"]
            ),
            "ambient_temp": float(
                payload["ambient_temp"]
            ),
            "cpu_load_pct": float(
                payload["cpu_load_pct"]
            ),
            "casing_installed_pct": float(
                payload["casing_installed_pct"]
            ),
            "clock_pct": float(
                payload["clock_pct"]
            ),
            "brightness_pct": float(
                payload["brightness_pct"]
            ),
            "is_charging": bool(
                payload["is_charging"]
            ),
            "thermal_level": int(
                payload["thermal_level"]
            ),
            "status": str(
                payload["status"]
            ).upper()
        }

        with shared["lock"]:
            shared["history"].append(record)
            shared["last_message"] = datetime.now()
            shared["error"] = None

    except (
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError
    ) as exc:
        with shared["lock"]:
            shared["error"] = (
                f"Payload MQTT tidak valid: {exc}"
            )


@st.cache_resource
def start_mqtt():
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=(
            f"thermal-dashboard-{int(time.time())}"
        )
    )

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    client.reconnect_delay_set(
        min_delay=1,
        max_delay=15
    )

    client.connect_async(
        MQTT_BROKER,
        MQTT_PORT,
        keepalive=60
    )

    client.loop_start()

    return client


try:
    mqtt_client = start_mqtt()

except Exception as exc:
    mqtt_client = None

    with shared["lock"]:
        shared["error"] = (
            f"Gagal memulai MQTT: {exc}"
        )


with shared["lock"]:
    history = list(shared["history"])
    connected = shared["connected"]
    last_message = shared["last_message"]
    mqtt_error = shared["error"]


if connected:
    st.success(
        "MQTT terhubung ke broker HiveMQ"
    )
else:
    st.warning(
        "Menghubungkan ke broker MQTT..."
    )


if mqtt_error:
    st.error(mqtt_error)


if last_message is not None:
    age = (
        datetime.now() - last_message
    ).total_seconds()

    if age > 10:
        st.warning(
            f"Tidak ada pesan baru selama {age:.0f} detik. "
            "Periksa simulasi Wokwi."
        )

if not history:
    st.info(
        "Menunggu data dari ESP32. Jalankan simulasi "
        "Wokwi dan pastikan topic MQTT sudah sesuai."
    )

    st.markdown("### Alur koneksi")
    st.code(
        "ESP32 / Wokwi → MQTT HiveMQ → Dashboard Python",
        language=None
    )

    st.stop()


df = pd.DataFrame(history)
latest = df.iloc[-1]

temperature = latest["soc_temperature"]
ambient = latest["ambient_temp"]
load = latest["cpu_load_pct"]
clock = latest["clock_pct"]
brightness = latest["brightness_pct"]
status = latest["status"]
charging = latest["is_charging"]
casing = latest["casing_installed_pct"] > 0

st.subheader("📊 Ringkasan Sistem")

c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "🌡️ Suhu SoC",
    f"{temperature:.1f} °C"
)

c2.metric(
    "🌤️ Suhu Lingkungan",
    f"{ambient:.1f} °C"
)

c3.metric(
    "⚡ Beban CPU",
    f"{load:.0f}%"
)

c4.metric(
    "🚀 Clock CPU",
    f"{clock:.0f}%"
)


st.subheader("🌡️ Status Thermal Throttling")

status_info = {
    "IDLE": ("🟢", "Suhu normal"),
    "RINGAN": ("🟡", "Suhu meningkat"),
    "BERAT": ("🟠", "Thermal throttling aktif"),
    "OVERHEAT": ("🔴", "Suhu mencapai zona kritis")
}

emoji, status_description = status_info.get(
    status,
    ("⚪", "Status tidak dikenal")
)

s1, s2, s3 = st.columns(3)

with s1:
    st.markdown(f"## {emoji} {status}")
    st.caption(status_description)

with s2:
    st.markdown("### 🔌 Charging")
    st.markdown(
        f"**{'Aktif' if charging else 'Nonaktif'}**"
    )

with s3:
    st.markdown("### 📱 Casing")
    st.markdown(
        f"**{'Terpasang' if casing else 'Dilepas'}**"
    )


if status == "OVERHEAT":
    st.error(
        "OVERHEAT: periksa alarm buzzer, penurunan "
        "clock CPU, dan kecerahan layar."
    )

elif status == "BERAT":
    st.warning(
        "Beban termal tinggi. Clock CPU telah dikurangi."
    )

elif status == "RINGAN":
    st.info(
        "Suhu berada pada level ringan."
    )

else:
    st.success(
        "Sistem berada pada kondisi idle."
    )


PLOT_TEMPLATE = (
    "plotly_dark"
    if st.session_state.dark_mode
    else "plotly_white"
)

AXIS_STYLE = {
    "gridcolor": GRID_COLOR,
    "linecolor": BORDER_COLOR,
    "zerolinecolor": GRID_COLOR,
    "showline": True,
    "ticks": "outside",
    "tickcolor": MUTED_COLOR
}


st.subheader("📈 Monitoring Suhu")

fig_temp = go.Figure()

fig_temp.add_trace(
    go.Scatter(
        x=df["time"],
        y=df["soc_temperature"],
        mode="lines",
        name="Suhu SoC",
        line=dict(
            color="#6366F1",
            width=3
        )
    )
)

fig_temp.add_trace(
    go.Scatter(
        x=df["time"],
        y=df["ambient_temp"],
        mode="lines",
        name="Suhu Lingkungan",
        line=dict(
            color="#F04438",
            width=2,
            dash="dash"
        )
    )
)


# Garis batas suhu 30°C
fig_temp.add_hline(
    y=30,
    line_dash="dot",
    line_color="#64748B",
    line_width=2,
    annotation_text="30°C - Ringan",
    annotation_position="right",
    annotation_font_color=TEXT_COLOR,
    annotation_font_size=12
)

# Garis batas suhu 37°C
fig_temp.add_hline(
    y=37,
    line_dash="dot",
    line_color="#64748B",
    line_width=2,
    annotation_text="37°C - Berat",
    annotation_position="right",
    annotation_font_color=TEXT_COLOR,
    annotation_font_size=12
)

# Garis batas suhu 44°C
fig_temp.add_hline(
    y=44,
    line_dash="dash",
    line_color="#334E7E",
    line_width=2,
    annotation_text="44°C - Overheat",
    annotation_position="right",
    annotation_font_color=TEXT_COLOR,
    annotation_font_size=12
)


fig_temp.update_layout(
    template=PLOT_TEMPLATE,
    paper_bgcolor=CARD_COLOR,
    plot_bgcolor=CARD_COLOR,

    font=dict(
        color=TEXT_COLOR,
        size=13
    ),

    xaxis=dict(
        **AXIS_STYLE,
        title=dict(
            text="Waktu",
            font=dict(
                color=TEXT_COLOR,
                size=14
            )
        ),
        tickfont=dict(
            color=TICK_COLOR,
            size=12
        ),
        tickformat="%H:%M:%S",
        automargin=True
    ),

    yaxis=dict(
        **AXIS_STYLE,
        title=dict(
            text="Suhu (°C)",
            font=dict(
                color=TEXT_COLOR,
                size=14
            )
        ),
        tickfont=dict(
            color=TICK_COLOR,
            size=13
        ),
        automargin=True
    ),

    hovermode="x unified",
    height=440,

    margin=dict(
        l=65,
        r=110,
        t=55,
        b=70
    ),

    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="left",
        x=0,
        font=dict(
            color=TEXT_COLOR,
            size=12
        )
    )
)

st.plotly_chart(
    fig_temp,
    use_container_width=True
)


st.subheader("⚙️ Beban CPU dan Clock")

fig_cpu = go.Figure()

fig_cpu.add_trace(
    go.Scatter(
        x=df["time"],
        y=df["cpu_load_pct"],
        mode="lines",
        name="Beban CPU",
        line=dict(
            color="#6366F1",
            width=3
        )
    )
)

fig_cpu.add_trace(
    go.Scatter(
        x=df["time"],
        y=df["clock_pct"],
        mode="lines",
        name="Clock CPU",
        line=dict(
            color="#F04438",
            width=3,
            dash="dash"
        )
    )
)


fig_cpu.update_layout(
    template=PLOT_TEMPLATE,
    paper_bgcolor=CARD_COLOR,
    plot_bgcolor=CARD_COLOR,

    font=dict(
        color=TEXT_COLOR,
        size=13
    ),

    xaxis=dict(
        **AXIS_STYLE,
        title=dict(
            text="Waktu",
            font=dict(
                color=TEXT_COLOR,
                size=14
            )
        ),
        tickfont=dict(
            color=TICK_COLOR,
            size=12
        ),
        tickformat="%H:%M:%S",
        automargin=True
    ),

    yaxis=dict(
        **AXIS_STYLE,
        title=dict(
            text="Persentase (%)",
            font=dict(
                color=TEXT_COLOR,
                size=14
            )
        ),
        tickfont=dict(
            color=TICK_COLOR,
            size=13
        ),
        range=[0, 105],
        dtick=20,
        automargin=True
    ),

    hovermode="x unified",
    height=380,

    margin=dict(
        l=65,
        r=30,
        t=55,
        b=70
    ),

    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="left",
        x=0,
        font=dict(
            color=TEXT_COLOR,
            size=12
        )
    )
)

st.plotly_chart(
    fig_cpu,
    use_container_width=True
)


st.subheader("💡 Kecerahan Layar")

st.progress(
    int(max(0, min(100, brightness))),
    text=f"Kecerahan layar: {brightness:.0f}%"
)

st.subheader("📋 Riwayat Telemetri")

with st.expander("Tampilkan data MQTT"):
    display_df = df.copy()

    display_df["time"] = (
        display_df["time"].dt.strftime("%H:%M:%S")
    )

    display_df = display_df.rename(
        columns={
            "time": "Waktu",
            "soc_temperature": "Suhu SoC (°C)",
            "ambient_temp": "Suhu Lingkungan (°C)",
            "cpu_load_pct": "Beban CPU (%)",
            "casing_installed_pct": "Casing (%)",
            "clock_pct": "Clock (%)",
            "brightness_pct": "Kecerahan (%)",
            "is_charging": "Charging",
            "thermal_level": "Level Termal",
            "status": "Status"
        }
    )

    st.dataframe(
        display_df.iloc[::-1],
        use_container_width=True,
        hide_index=True
    )

st.subheader("📊 Statistik Sesi")

m1, m2, m3 = st.columns(3)

m1.metric(
    "Suhu SoC Minimum",
    f"{df['soc_temperature'].min():.1f} °C"
)

m2.metric(
    "Suhu SoC Maksimum",
    f"{df['soc_temperature'].max():.1f} °C"
)

m3.metric(
    "Jumlah Data",
    f"{len(df)}"
)


st.divider()

f1, f2 = st.columns(2)

with f1:
    st.caption(
        "Smartphone Thermal Throttling | SIC"
    )

with f2:
    st.caption(
        f"Broker: {MQTT_BROKER}:{MQTT_PORT} | "
        f"Topic: {MQTT_TOPIC}"
    )

st.caption(
    "Dashboard menampilkan maksimal 300 pesan terakhir "
    "selama aplikasi berjalan. Broker MQTT yang digunakan "
    "adalah broker publik, sehingga pesan tidak bersifat privat."
)
