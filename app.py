import sqlite3
import json
import tempfile
import os

import blackboxprotobuf
import streamlit as st

st.set_page_config(
    page_title="Teamspeak 6 Extractor",
    page_icon="🔍",
    layout="wide",
)

TS_UUID = "11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def get_connection(db_path: str) -> sqlite3.Connection:
    uri = f"file:{db_path}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.text_factory = bytes
    return conn


def with_conn(fn, *args, **kwargs):
    conn = get_connection(st.session_state["db_path_open"])
    try:
        return fn(conn, *args, **kwargs)
    finally:
        conn.close()


def fetch_all_rows(conn: sqlite3.Connection) -> list[tuple]:
    cursor = conn.cursor()
    cursor.execute("SELECT rowid, key FROM ProtobufItems ORDER BY rowid")
    return cursor.fetchall()


def fetch_row(conn: sqlite3.Connection, rowid: int) -> bytes | None:
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM ProtobufItems WHERE rowid=?", (rowid,))
    row = cursor.fetchone()
    if row is None:
        return None
    blob = row[0]
    if isinstance(blob, str):
        blob = blob.encode("latin1")
    return blob


def decode_blob(blob: bytes) -> tuple[dict, dict]:
    return blackboxprotobuf.decode_message(blob)


def make_json_serialisable(obj):
    if isinstance(obj, bytes):
        return obj.decode("latin1")
    if isinstance(obj, dict):
        return {k: make_json_serialisable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_json_serialisable(i) for i in obj]
    return obj


def to_str(val) -> str:
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val) if val is not None else ""


def message_contains_uuid(obj) -> bool:
    if isinstance(obj, (bytes, str)):
        return TS_UUID in to_str(obj)
    if isinstance(obj, dict):
        return any(message_contains_uuid(v) for v in obj.values())
    if isinstance(obj, list):
        return any(message_contains_uuid(v) for v in obj)
    return False


def extract_credentials(message: dict) -> dict | None:
    block21 = message.get("21") or message.get(21)
    if not isinstance(block21, dict):
        return None
    block5 = block21.get("5") or block21.get(5)
    if not isinstance(block5, dict):
        return None
    homeserver = to_str(block5.get("1") or block5.get(1) or "")
    username   = to_str(block5.get("2") or block5.get(2) or "")
    password   = to_str(block5.get("3") or block5.get(3) or "")
    if not any([homeserver, username, password]):
        return None
    return {"homeserver": homeserver, "username": username, "password": password}


def sort_rows(rows: list[tuple], messages: dict) -> list[tuple]:
    """
    3-tier sort priority:
      0 — UUID present AND credentials found at ["21"]["5"]  (best match)
      1 — UUID present but no credentials
      2 — everything else
    """
    def key(item):
        rowid, _ = item
        msg = messages.get(rowid, {})
        has_uuid  = message_contains_uuid(msg)
        has_creds = extract_credentials(msg) is not None
        if has_uuid and has_creds:
            return 0
        if has_uuid:
            return 1
        return 2
    return sorted(rows, key=key)


def _init_state():
    defaults = {
        "db_path": "",
        "db_temp_path": None,
        "db_path_open": None,
        "rows": [],
        "row_messages": {},
        "selected_rowid": None,
        "blob": None,
        "message": None,
        "typedef": None,
        "edit_json": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()


def load_all_messages(db_path: str, rows: list[tuple]) -> dict:
    messages = {}
    conn = get_connection(db_path)
    try:
        for rowid, _ in rows:
            blob = fetch_row(conn, rowid)
            if blob:
                try:
                    msg, _ = decode_blob(blob)
                    messages[rowid] = msg
                except Exception:
                    messages[rowid] = {}
    finally:
        conn.close()
    return messages


def open_db(path: str):
    conn = get_connection(path)
    rows = fetch_all_rows(conn)
    conn.close()

    row_messages = load_all_messages(path, rows)
    sorted_rows = sort_rows(rows, row_messages)

    st.session_state["db_path_open"] = path
    st.session_state["rows"] = sorted_rows
    st.session_state["row_messages"] = row_messages
    st.session_state["selected_rowid"] = None
    st.session_state["blob"] = None
    st.session_state["message"] = None
    st.session_state["typedef"] = None
    st.session_state["edit_json"] = ""


def load_row(rowid: int):
    blob = with_conn(fetch_row, rowid)
    if blob:
        message, typedef = decode_blob(blob)
        st.session_state["selected_rowid"] = rowid
        st.session_state["blob"] = blob
        st.session_state["message"] = message
        st.session_state["typedef"] = typedef
        st.session_state["edit_json"] = json.dumps(
            make_json_serialisable(message), indent=2
        )


with st.sidebar:
    st.markdown(
        "Upload your local `settings.db` file, drag & drop or click to choose. "
    )

    uploaded = st.file_uploader(
        "Upload settings.db",
        type=["db", "sqlite", "sqlite3"],
        accept_multiple_files=False,
    )

    if uploaded is not None:
        prev_tmp = st.session_state.get("db_temp_path")
        if prev_tmp and os.path.exists(prev_tmp):
            try:
                os.remove(prev_tmp)
            except Exception:
                pass

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        tmp.write(uploaded.getvalue())
        tmp.flush()
        tmp.close()
        st.session_state["db_temp_path"] = tmp.name
        st.session_state["db_path"] = tmp.name

        try:
            open_db(tmp.name)
            st.success("Database opened read-only")
        except Exception as exc:
            st.error(f"Could not open uploaded database: {exc}")

    st.divider()

    if st.session_state["db_path_open"]:
        rows = st.session_state["rows"]
        row_messages = st.session_state["row_messages"]

        def row_label(rowid, key) -> str:
            label = key.decode("utf-8", errors="replace") if isinstance(key, bytes) else str(key)
            msg = row_messages.get(rowid, {})
            has_uuid  = message_contains_uuid(msg)
            has_creds = extract_credentials(msg) is not None
            if has_uuid and has_creds:
                prefix = "🔑 "
            elif has_uuid:
                prefix = "⭐ "
            else:
                prefix = ""
            return f"{prefix}rowid {rowid} — {label}"

        labels = [row_label(rowid, key) for rowid, key in rows]
        choice = st.selectbox("Select row", options=labels, index=0)
        idx = labels.index(choice)
        selected_rowid = rows[idx][0]

        if selected_rowid != st.session_state.get("selected_rowid"):
            try:
                load_row(selected_rowid)
            except Exception as exc:
                st.error(f"Failed to decode row: {exc}")

        st.divider()
        if st.button("Close database", use_container_width=True):
            tmp = st.session_state.get("db_temp_path")
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception:
                    pass
            for k in ["db_path", "db_temp_path", "db_path_open", "rows",
                      "row_messages", "selected_rowid", "blob", "message",
                      "typedef", "edit_json"]:
                st.session_state[k] = [] if k == "rows" else ({} if k == "row_messages" else None if k != "db_path" else "")
            st.rerun()

if not st.session_state["db_path_open"]:
    st.markdown(
        """
        ## Teamspeak 6 Matrix Credential Extractor

        This is a tool built for extracting your Matrix credentials from Teamspeak 6 to access the chat functionalities from Matrix compatible clients.

        ### Usage
        Using the sidebar, load your `settings.db. You can find it in the locations listed below:

        - Windows: `%APPDATA%\TeamSpeak\Default`
        - Linux: `~/.config/TeamSpeak/Default`
        - Mac: `~/Library/Preferences/TeamSpeak/Default`

        ### Limitations
        Only unencrypted group chats will work properly, encrypted chat is extremely flakey.

        Teamspeak has various custom tools built-on top of the Matrix protocol
        so not everything is supported/compatible. **Use at your own risk**
        """
    )
    st.stop()

if not st.session_state["selected_rowid"]:
    st.info("Select a row from the sidebar to inspect it.")
    st.stop()

rowid  = st.session_state["selected_rowid"]
message = st.session_state["message"]

st.header(f"Row `{rowid}`")

creds = extract_credentials(message) if message else None
if creds:
    st.success("✅ Matrix credentials found in this row!")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Home server**")
        st.code(creds["homeserver"])
    with c2:
        st.markdown("**Username (yes it's that long)**")
        st.code(creds["username"])
    with c3:
        st.markdown("**Password**")
        st.code(creds["password"])
    st.caption("Use the information here to login to your favorite Matrix client!")
    st.caption(f"Your full Matrix username is {creds["username"]}@{creds["homeserver"]}")

    st.divider()
elif message:
    st.info('No credentials found in this row, try choosing a different one')

tab_decoded, tab_typedef, tab_view, tab_raw = st.tabs([
    "📋 Decoded",
    "🗂 Type definition",
    "🔍 Read-only view",
    "🔢 Raw bytes",
])

with tab_decoded:
    if message is not None:
        st.json(make_json_serialisable(message), expanded=True)
    else:
        st.warning("No decoded message available.")

with tab_typedef:
    if st.session_state["typedef"] is not None:
        st.json(st.session_state["typedef"], expanded=True)
    else:
        st.warning("No type definition available.")

with tab_view:
    if st.session_state["edit_json"]:
        st.code(st.session_state["edit_json"], language="json")
    else:
        st.warning("No message to display.")

with tab_raw:
    blob = st.session_state["blob"]
    if blob:
        col_info, col_dl = st.columns([3, 1])
        with col_info:
            st.metric("Blob size", f"{len(blob):,} bytes")
        if st.checkbox("Show raw hex"):
            hex_str = blob.hex()
            lines = []
            for i in range(0, len(hex_str), 32):
                offset = i // 2
                chunk = hex_str[i : i + 32]
                spaced = " ".join(chunk[j : j + 2] for j in range(0, len(chunk), 2))
                lines.append(f"{offset:06x}  {spaced}")
            st.code("\n".join(lines), language="none")
    else:
        st.warning("No blob data available.")
