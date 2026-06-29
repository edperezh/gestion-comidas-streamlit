from __future__ import annotations

import calendar
import hashlib
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import streamlit as st

# ============================================================
# CONFIGURACIÓN DEL NEGOCIO
# ============================================================
APP_TITLE = "Gestión de Comidas"
MONTHLY_TICKET_VALUE = 480_000
BREAKFAST_LIMIT = 30
LUNCH_LIMIT = 30
BREAKFAST_PRICE = 7_000
LUNCH_PRICE = 9_000  # 30*7.000 + 30*9.000 = 480.000
DB_PATH = Path("comidas.db")

MEAL_LABELS = {
    "desayuno": "Desayuno",
    "almuerzo": "Almuerzo",
}

MEAL_EMOJIS = {
    "desayuno": "☕",
    "almuerzo": "🍛",
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# ============================================================
# UTILIDADES
# ============================================================

def money(value: float | int) -> str:
    return f"${int(round(value)):,.0f}".replace(",", ".")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(normalize_email(email)))


def month_range(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    last = date(year, month, last_day)
    return first, last


def month_name_es(month: int) -> str:
    names = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
        7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
    }
    return names[month]


def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()


def has_supabase_config() -> bool:
    try:
        return bool(st.secrets.get("SUPABASE_URL") and st.secrets.get("SUPABASE_KEY"))
    except Exception:
        return False


# ============================================================
# REPOSITORIOS DE DATOS
# ============================================================
@dataclass
class MealLog:
    id: str
    email: str
    meal_date: str
    meal_type: str
    created_at: str


class SQLiteRepo:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.init_db()

    def connect(self):
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    email TEXT PRIMARY KEY,
                    name TEXT,
                    pin_hash TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meal_logs (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    meal_date TEXT NOT NULL,
                    meal_type TEXT NOT NULL CHECK(meal_type IN ('desayuno', 'almuerzo')),
                    created_at TEXT NOT NULL,
                    UNIQUE(email, meal_date, meal_type)
                )
                """
            )
            conn.commit()

    def ensure_user(self, email: str, name: str = "", pin: str = "") -> None:
        now = datetime.now().isoformat(timespec="seconds")
        pin_hash = hash_pin(pin) if pin else ""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO users(email, name, pin_hash, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    name = CASE WHEN excluded.name != '' THEN excluded.name ELSE users.name END,
                    pin_hash = CASE WHEN excluded.pin_hash != '' THEN excluded.pin_hash ELSE users.pin_hash END
                """,
                (email, name, pin_hash, now),
            )
            conn.commit()

    def user_exists(self, email: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone()
            return row is not None

    def verify_pin(self, email: str, pin: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT pin_hash FROM users WHERE email=?", (email,)).fetchone()
            if row is None:
                return False
            saved = row[0] or ""
            return not saved or saved == hash_pin(pin)

    def add_meal(self, email: str, meal_date: date, meal_type: str) -> tuple[bool, str]:
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with self.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO meal_logs(id, email, meal_date, meal_type, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), email, meal_date.isoformat(), meal_type, now),
                )
                conn.commit()
            return True, f"{MEAL_LABELS[meal_type]} registrado para {meal_date.isoformat()}."
        except sqlite3.IntegrityError:
            return False, f"Ya tenías registrado {MEAL_LABELS[meal_type].lower()} ese día."

    def delete_meal(self, email: str, meal_date: date, meal_type: str) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM meal_logs WHERE email=? AND meal_date=? AND meal_type=?",
                (email, meal_date.isoformat(), meal_type),
            )
            conn.commit()
            return cur.rowcount

    def get_month_logs(self, email: str, year: int, month: int) -> pd.DataFrame:
        first, last = month_range(year, month)
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, email, meal_date, meal_type, created_at
                FROM meal_logs
                WHERE email=? AND meal_date BETWEEN ? AND ?
                ORDER BY meal_date, meal_type
                """,
                (email, first.isoformat(), last.isoformat()),
            ).fetchall()
        return pd.DataFrame(rows, columns=["id", "email", "meal_date", "meal_type", "created_at"])


class SupabaseRepo:
    def __init__(self):
        from supabase import create_client

        self.client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

    def ensure_user(self, email: str, name: str = "", pin: str = "") -> None:
        now = datetime.now().isoformat(timespec="seconds")
        pin_hash = hash_pin(pin) if pin else ""

        existing = self.client.table("users_meals").select("email,name,pin_hash").eq("email", email).execute().data
        if existing:
            updates: dict[str, Any] = {}
            if name:
                updates["name"] = name
            if pin_hash:
                updates["pin_hash"] = pin_hash
            if updates:
                self.client.table("users_meals").update(updates).eq("email", email).execute()
        else:
            self.client.table("users_meals").insert(
                {"email": email, "name": name, "pin_hash": pin_hash, "created_at": now}
            ).execute()

    def user_exists(self, email: str) -> bool:
        data = self.client.table("users_meals").select("email").eq("email", email).limit(1).execute().data
        return bool(data)

    def verify_pin(self, email: str, pin: str) -> bool:
        data = self.client.table("users_meals").select("pin_hash").eq("email", email).limit(1).execute().data
        if not data:
            return False
        saved = data[0].get("pin_hash") or ""
        return not saved or saved == hash_pin(pin)

    def add_meal(self, email: str, meal_date: date, meal_type: str) -> tuple[bool, str]:
        existing = (
            self.client.table("meal_logs")
            .select("id")
            .eq("email", email)
            .eq("meal_date", meal_date.isoformat())
            .eq("meal_type", meal_type)
            .limit(1)
            .execute()
            .data
        )
        if existing:
            return False, f"Ya tenías registrado {MEAL_LABELS[meal_type].lower()} ese día."

        self.client.table("meal_logs").insert(
            {
                "id": str(uuid.uuid4()),
                "email": email,
                "meal_date": meal_date.isoformat(),
                "meal_type": meal_type,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
        ).execute()
        return True, f"{MEAL_LABELS[meal_type]} registrado para {meal_date.isoformat()}."

    def delete_meal(self, email: str, meal_date: date, meal_type: str) -> int:
        data = (
            self.client.table("meal_logs")
            .delete()
            .eq("email", email)
            .eq("meal_date", meal_date.isoformat())
            .eq("meal_type", meal_type)
            .execute()
            .data
        )
        return len(data or [])

    def get_month_logs(self, email: str, year: int, month: int) -> pd.DataFrame:
        first, last = month_range(year, month)
        data = (
            self.client.table("meal_logs")
            .select("id,email,meal_date,meal_type,created_at")
            .eq("email", email)
            .gte("meal_date", first.isoformat())
            .lte("meal_date", last.isoformat())
            .order("meal_date")
            .execute()
            .data
        )
        df = pd.DataFrame(data or [], columns=["id", "email", "meal_date", "meal_type", "created_at"])
        return df


@st.cache_resource(show_spinner=False)
def get_repo():
    if has_supabase_config():
        return SupabaseRepo(), "Supabase"
    return SQLiteRepo(DB_PATH), "SQLite local"


# ============================================================
# INTERFAZ
# ============================================================
st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🍽️",
    layout="wide",
)

st.markdown(
    """
    <style>
        .main-title {font-size: 2.2rem; font-weight: 800; margin-bottom: 0.2rem;}
        .subtitle {color: rgba(250,250,250,.72); margin-bottom: 1rem;}
        .calendar-grid {display: grid; grid-template-columns: repeat(7, 1fr); gap: 8px;}
        .day-card {border: 1px solid rgba(128,128,128,.25); border-radius: 12px; padding: 10px; min-height: 82px;}
        .day-number {font-weight: 700; font-size: .95rem;}
        .meal-chip {display: inline-block; border-radius: 999px; padding: 2px 8px; margin: 4px 4px 0 0; background: rgba(128,128,128,.12); font-size: .85rem;}
        .empty-day {opacity: .35;}
    </style>
    """,
    unsafe_allow_html=True,
)

repo, storage_mode = get_repo()

st.markdown(f"<div class='main-title'>🍽️ {APP_TITLE}</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='subtitle'>Control mensual de desayunos y almuerzos por usuario.</div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("👤 Perfil")
    email_input = st.text_input("Correo", placeholder="tu.correo@email.com")
    name_input = st.text_input("Nombre opcional", placeholder="Ej: Yeyson")
    pin_input = st.text_input("PIN opcional", type="password", help="Sirve para que otra persona no entre solo escribiendo tu correo.")

    col_login, col_create = st.columns(2)
    with col_create:
        create_clicked = st.button("Guardar perfil", use_container_width=True)
    with col_login:
        login_clicked = st.button("Entrar", type="primary", use_container_width=True)

    st.divider()
    st.caption(f"Almacenamiento: {storage_mode}")
    if storage_mode == "SQLite local":
        st.warning(
            "Modo local: sirve solo para pruebas. Para usar el link con varios usuarios, configura Supabase en Streamlit Cloud.",
            icon="⚠️",
        )

if create_clicked:
    email = normalize_email(email_input)
    if not valid_email(email):
        st.sidebar.error("Escribe un correo válido.")
    else:
        repo.ensure_user(email, name_input.strip(), pin_input.strip())
        st.session_state["user_email"] = email
        st.sidebar.success("Perfil listo.")

if login_clicked:
    email = normalize_email(email_input)
    if not valid_email(email):
        st.sidebar.error("Escribe un correo válido.")
    elif not repo.user_exists(email):
        st.sidebar.error("Ese correo aún no tiene perfil. Créalo primero.")
    elif not repo.verify_pin(email, pin_input.strip()):
        st.sidebar.error("PIN incorrecto.")
    else:
        st.session_state["user_email"] = email
        st.sidebar.success("Sesión iniciada.")

email = st.session_state.get("user_email")
if not email:
    st.info("Ingresa o crea tu perfil desde la barra lateral para empezar a registrar comidas.")
    st.stop()

# Selector mensual
today = date.today()
left, mid, right = st.columns([1, 1, 2])
with left:
    selected_year = st.number_input("Año", min_value=2020, max_value=2100, value=today.year, step=1)
with mid:
    selected_month = st.selectbox(
        "Mes",
        options=list(range(1, 13)),
        index=today.month - 1,
        format_func=month_name_es,
    )
with right:
    st.write("")
    st.success(f"Perfil activo: {email}")

selected_year = int(selected_year)
selected_month = int(selected_month)
logs = repo.get_month_logs(email, selected_year, selected_month)

if logs.empty:
    breakfast_count = 0
    lunch_count = 0
else:
    breakfast_count = int((logs["meal_type"] == "desayuno").sum())
    lunch_count = int((logs["meal_type"] == "almuerzo").sum())

breakfast_left = max(BREAKFAST_LIMIT - breakfast_count, 0)
lunch_left = max(LUNCH_LIMIT - lunch_count, 0)
used_value = breakfast_count * BREAKFAST_PRICE + lunch_count * LUNCH_PRICE
remaining_value = max(MONTHLY_TICKET_VALUE - used_value, 0)
progress = min((breakfast_count + lunch_count) / (BREAKFAST_LIMIT + LUNCH_LIMIT), 1)

st.subheader(f"Resumen de {month_name_es(selected_month)} {selected_year}")
metric_cols = st.columns(6)
metric_cols[0].metric("Desayunos usados", breakfast_count, f"Faltan {breakfast_left}")
metric_cols[1].metric("Almuerzos usados", lunch_count, f"Faltan {lunch_left}")
metric_cols[2].metric("Total comidas", breakfast_count + lunch_count, f"de {BREAKFAST_LIMIT + LUNCH_LIMIT}")
metric_cols[3].metric("Consumido", money(used_value))
metric_cols[4].metric("Saldo estimado", money(remaining_value))
metric_cols[5].metric("Tiquetera", money(MONTHLY_TICKET_VALUE))
st.progress(progress, text=f"Uso mensual: {progress:.0%}")

st.divider()

# Registro rápido
st.subheader("Registrar comida")
reg_col1, reg_col2, reg_col3, reg_col4 = st.columns([1.2, 1, 1, 1])
with reg_col1:
    register_date = st.date_input("Fecha", value=today)
with reg_col2:
    if st.button("☕ Registrar desayuno", use_container_width=True):
        ok, msg = repo.add_meal(email, register_date, "desayuno")
        if ok:
            st.success(msg)
            st.rerun()
        else:
            st.warning(msg)
with reg_col3:
    if st.button("🍛 Registrar almuerzo", use_container_width=True):
        ok, msg = repo.add_meal(email, register_date, "almuerzo")
        if ok:
            st.success(msg)
            st.rerun()
        else:
            st.warning(msg)
with reg_col4:
    meal_to_delete = st.selectbox("Borrar", ["desayuno", "almuerzo"], format_func=lambda x: MEAL_LABELS[x])
    if st.button("Eliminar registro", use_container_width=True):
        deleted = repo.delete_meal(email, register_date, meal_to_delete)
        if deleted:
            st.success("Registro eliminado.")
            st.rerun()
        else:
            st.info("No había registro para eliminar.")

st.divider()

# Calendario mensual
st.subheader("Calendario del mes")
logs_by_day: dict[str, set[str]] = {}
if not logs.empty:
    for _, row in logs.iterrows():
        logs_by_day.setdefault(row["meal_date"], set()).add(row["meal_type"])

weekdays = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
header_html = "".join([f"<div class='day-card'><b>{d}</b></div>" for d in weekdays])
cal = calendar.Calendar(firstweekday=0)
weeks = cal.monthdatescalendar(selected_year, selected_month)
body_html = ""
for week in weeks:
    for d in week:
        is_current = d.month == selected_month
        classes = "day-card" if is_current else "day-card empty-day"
        meals = logs_by_day.get(d.isoformat(), set()) if is_current else set()
        chips = "".join(
            f"<span class='meal-chip'>{MEAL_EMOJIS[m]} {MEAL_LABELS[m]}</span>"
            for m in ["desayuno", "almuerzo"]
            if m in meals
        )
        body_html += f"<div class='{classes}'><div class='day-number'>{d.day}</div>{chips}</div>"

st.markdown(f"<div class='calendar-grid'>{header_html}{body_html}</div>", unsafe_allow_html=True)

st.divider()

# Detalle y exportación
st.subheader("Detalle de registros")
if logs.empty:
    st.write("Aún no hay registros en este mes.")
else:
    detail = logs.copy()
    detail["Tipo"] = detail["meal_type"].map(MEAL_LABELS)
    detail["Fecha"] = pd.to_datetime(detail["meal_date"]).dt.date
    detail["Valor"] = detail["meal_type"].map({"desayuno": BREAKFAST_PRICE, "almuerzo": LUNCH_PRICE})
    st.dataframe(detail[["Fecha", "Tipo", "Valor", "created_at"]], use_container_width=True, hide_index=True)

    csv = detail[["Fecha", "Tipo", "Valor", "created_at"]].to_csv(index=False).encode("utf-8")
    st.download_button(
        "Descargar CSV del mes",
        data=csv,
        file_name=f"comidas_{email}_{selected_year}_{selected_month:02d}.csv".replace("@", "_"),
        mime="text/csv",
    )

st.caption(
    "Nota: esta app separa perfiles por correo y PIN. Para seguridad avanzada, conviene agregar inicio de sesión con Google más adelante."
)
