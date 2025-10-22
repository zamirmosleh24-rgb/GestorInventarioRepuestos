#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Servidor para GestorInventarioRepuestos (VERSIÓN SIN GOOGLE DRIVE)

Funciones incluidas:
- Tkinter GUI (estilo moderno Windows 10)
- Flask API embebida (hilo separado) en puerto 5000
- SQLite local (server_data.db) creada automáticamente
- Backups locales (diario al iniciar + manuales)
- Restauración desde backups locales (GUI)
- Sincronización instantánea: endpoint /last_update
- Seguridad: API key (api_key.txt) creada/cambiada desde GUI
- Logs guardados en archivo y muestra de últimos eventos en GUI
- Control de clientes conectados (último ping)
"""

import os
import sys
import sqlite3
import threading
import shutil
import socket
from datetime import datetime
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

# -------------------------
# Configuración
# -------------------------
DB_FILE = "server_data.db"
BACKUPS_DIR = "backups"
API_KEY_FILE = "api_key.txt"
LOGS_DIR = "logs"
LOG_FILE = os.path.join(LOGS_DIR, "server_log.txt")
HOST = "0.0.0.0"
PORT = 5000
GUI_MAX_LOG_LINES = 50

# -------------------------
# Utilidades
# -------------------------
def ensure_dirs():
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)

def now_ts():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # connect to external DNS to determine local IP (no traffic sent)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

# -------------------------
# Logging (archivo + UI)
# -------------------------
LOG_LINES = []
LOG_LOCK = threading.Lock()

def append_log_file(text):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass

def log(msg):
    ts = now_ts()
    line = f"[{ts}] {msg}"
    with LOG_LOCK:
        LOG_LINES.append(line)
        # keep bounded history for UI
        if len(LOG_LINES) > 2000:
            LOG_LINES[:] = LOG_LINES[-2000:]
    append_log_file(line)

# -------------------------
# DB (concurrency-safe)
# -------------------------
DB_LOCK = threading.Lock()

class ServerDB:
    def __init__(self, filename=DB_FILE):
        self.filename = filename
        self._connect()

    def _connect(self):
        first = not os.path.exists(self.filename)
        # timeout to wait for locks
        self.conn = sqlite3.connect(self.filename, check_same_thread=False, timeout=10)
        self.conn.row_factory = sqlite3.Row
        if first:
            self._init_schema()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def _init_schema(self):
        with DB_LOCK:
            c = self.conn.cursor()
            c.execute("""
            CREATE TABLE IF NOT EXISTS repuestos (
                id TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                descripcion TEXT,
                cantidad INTEGER NOT NULL DEFAULT 0,
                precio_usd REAL NOT NULL DEFAULT 0.0,
                precio_bs REAL NOT NULL DEFAULT 0.0,
                ultimo_update TEXT,
                deleted INTEGER DEFAULT 0
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS ventas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT,
                cantidad INTEGER,
                fecha TEXT
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS devoluciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT,
                cantidad INTEGER,
                fecha TEXT
            )
            """)
            self.conn.commit()

    def export_db_path(self):
        return os.path.abspath(self.filename)

    def get_all(self):
        with DB_LOCK:
            c = self.conn.cursor()
            c.execute("SELECT * FROM repuestos WHERE deleted=0")
            return [dict(r) for r in c.fetchall()]

    def get_one(self, item_id):
        with DB_LOCK:
            c = self.conn.cursor()
            c.execute("SELECT * FROM repuestos WHERE id=? AND deleted=0", (item_id,))
            r = c.fetchone()
            return dict(r) if r else None

    def upsert(self, item):
        item.setdefault("ultimo_update", now_ts())
        with DB_LOCK:
            c = self.conn.cursor()
            c.execute("""
              INSERT INTO repuestos (id,nombre,descripcion,cantidad,precio_usd,precio_bs,ultimo_update,deleted)
              VALUES (:id,:nombre,:descripcion,:cantidad,:precio_usd,:precio_bs,:ultimo_update,0)
              ON CONFLICT(id) DO UPDATE SET
                nombre=excluded.nombre,
                descripcion=excluded.descripcion,
                cantidad=excluded.cantidad,
                precio_usd=excluded.precio_usd,
                precio_bs=excluded.precio_bs,
                ultimo_update=excluded.ultimo_update,
                deleted=0
            """, item)
            self.conn.commit()

    def mark_deleted(self, item_id):
        with DB_LOCK:
            c = self.conn.cursor()
            c.execute("UPDATE repuestos SET deleted=1, ultimo_update=? WHERE id=?", (now_ts(), item_id))
            self.conn.commit()

    def sell(self, item_id, quantity):
        with DB_LOCK:
            c = self.conn.cursor()
            c.execute("SELECT cantidad FROM repuestos WHERE id=? AND deleted=0", (item_id,))
            r = c.fetchone()
            if not r:
                return False, "Artículo no encontrado"
            available = r["cantidad"]
            if quantity > available:
                return False, "Stock insuficiente"
            newq = available - quantity
            c.execute("UPDATE repuestos SET cantidad=?, ultimo_update=? WHERE id=?", (newq, now_ts(), item_id))
            c.execute("INSERT INTO ventas (item_id,cantidad,fecha) VALUES (?,?,?)", (item_id, quantity, now_ts()))
            self.conn.commit()
            return True, newq

    def add_quantity(self, item_id, quantity):
        with DB_LOCK:
            c = self.conn.cursor()
            c.execute("SELECT cantidad FROM repuestos WHERE id=? AND deleted=0", (item_id,))
            r = c.fetchone()
            if not r:
                return False, "Artículo no encontrado"
            newq = r["cantidad"] + quantity
            c.execute("UPDATE repuestos SET cantidad=?, ultimo_update=? WHERE id=?", (newq, now_ts(), item_id))
            c.execute("INSERT INTO devoluciones (item_id,cantidad,fecha) VALUES (?,?,?)", (item_id, quantity, now_ts()))
            self.conn.commit()
            return True, newq

# -------------------------
# Estado global
# -------------------------
ensure_dirs()
db = ServerDB()
app = Flask(__name__)
CORS(app)

# last_update para sincronización
LAST_UPDATE_LOCK = threading.Lock()
LAST_UPDATE = now_ts()

CLIENTS_LAST_SEEN = {}
CLIENTS_LOCK = threading.Lock()

def update_last_update():
    global LAST_UPDATE
    with LAST_UPDATE_LOCK:
        LAST_UPDATE = now_ts()
    log(f"GLOBAL last_update actualizado a {LAST_UPDATE}")

def get_last_update():
    with LAST_UPDATE_LOCK:
        return LAST_UPDATE

def update_client_seen(client_id):
    if not client_id:
        return
    with CLIENTS_LOCK:
        CLIENTS_LAST_SEEN[client_id] = datetime.utcnow()

def get_clients_snapshot():
    now = datetime.utcnow()
    out = []
    with CLIENTS_LOCK:
        for cid, dt in CLIENTS_LAST_SEEN.items():
            diff = now - dt
            out.append({"client_id": cid, "last_seen": dt.isoformat(), "seconds_ago": int(diff.total_seconds())})
    return out

# -------------------------
# API Key helper
# -------------------------
def read_api_key():
    if not os.path.exists(API_KEY_FILE):
        return None
    try:
        with open(API_KEY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None

def write_api_key(newkey):
    try:
        with open(API_KEY_FILE, "w", encoding="utf-8") as f:
            f.write(newkey.strip())
    except Exception as e:
        log(f"Error escribiendo API key: {e}")

def require_api_key(f):
    def wrapper(*args, **kwargs):
        server_key = read_api_key()
        if server_key is None:
            return jsonify({"error": "server_api_key_no_configurada"}), 403
        header = request.headers.get("X-API-KEY", "")
        if not header or header != server_key:
            log(f"Intento no autorizado desde {request.remote_addr} a {request.path}")
            return jsonify({"error": "api_key_invalida_o_faltante"}), 401
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# -------------------------
# Endpoints Flask
# -------------------------
@app.route("/ping", methods=["GET"])
def ping():
    client_id = request.headers.get("X-CLIENT-ID", None)
    update_client_seen(client_id)
    return jsonify({"ok": True, "server_time": now_ts(), "last_update": get_last_update()})

@app.route("/last_update", methods=["GET"])
def last_update():
    return jsonify({"last_update": get_last_update()})

@app.route("/items", methods=["GET", "POST"])
@require_api_key
def items():
    if request.method == "GET":
        items = db.get_all()
        return jsonify({"items": items, "server_time": now_ts(), "last_update": get_last_update()})
    else:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON recibido"}), 400
        item = data
        if "id" not in item:
            return jsonify({"error": "id es requerido"}), 400
        item.setdefault("ultimo_update", now_ts())
        db.upsert(item)
        update_last_update()
        log(f"Upsert item {item.get('id')} nombre='{item.get('nombre')}'")
        return jsonify({"ok": True, "item": item})

@app.route("/items/<item_id>", methods=["GET", "PUT", "DELETE"])
@require_api_key
def item_by_id(item_id):
    if request.method == "GET":
        it = db.get_one(item_id)
        if not it:
            return jsonify({"error": "no encontrado"}), 404
        return jsonify(it)
    elif request.method == "PUT":
        data = request.get_json()
        if not data:
            return jsonify({"error":"no json"}), 400
        data["id"] = item_id
        data.setdefault("ultimo_update", now_ts())
        db.upsert(data)
        update_last_update()
        log(f"PUT /items/{item_id}")
        return jsonify({"ok": True, "item": data})
    else:
        db.mark_deleted(item_id)
        update_last_update()
        log(f"DELETE /items/{item_id}")
        return jsonify({"ok": True})

@app.route("/sell", methods=["POST"])
@require_api_key
def sell():
    payload = request.get_json()
    if not payload:
        return jsonify({"error": "no json"}), 400
    item_id = payload.get("id")
    qty = int(payload.get("quantity", 1))
    ok, res = db.sell(item_id, qty)
    if not ok:
        log(f"Venta fallida {item_id} qty={qty} - {res}")
        return jsonify({"ok": False, "error": res}), 400
    it = db.get_one(item_id)
    update_last_update()
    log(f"Venta {item_id} qty={qty}")
    return jsonify({"ok": True, "new_quantity": res, "item": it})

@app.route("/return", methods=["POST"])
@require_api_key
def ret():
    payload = request.get_json()
    if not payload:
        return jsonify({"error": "no json"}), 400
    item_id = payload.get("id")
    qty = int(payload.get("quantity", 1))
    ok, res = db.add_quantity(item_id, qty)
    if not ok:
        log(f"Devolución fallida {item_id} qty={qty} - {res}")
        return jsonify({"ok": False, "error": res}), 400
    it = db.get_one(item_id)
    update_last_update()
    log(f"Devolución {item_id} qty={qty}")
    return jsonify({"ok": True, "new_quantity": res, "item": it})

@app.route("/backup", methods=["POST"])
@require_api_key
def backup():
    try:
        if not os.path.exists(BACKUPS_DIR):
            os.makedirs(BACKUPS_DIR, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        dest = os.path.join(BACKUPS_DIR, f"backup_{timestamp}.db")
        src = db.export_db_path()
        with DB_LOCK:
            db.conn.commit()
            db.conn.close()
            shutil.copyfile(src, dest)
            db._connect()
        log(f"Backup creado: {dest}")
        return jsonify({"ok": True, "local_copy": dest})
    except Exception as e:
        log(f"Error backup: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/list_backups", methods=["GET"])
@require_api_key
def list_backups():
    files = []
    if os.path.exists(BACKUPS_DIR):
        files = sorted(os.listdir(BACKUPS_DIR), reverse=True)
    return jsonify({"backups": files})

@app.route("/download_backup/<fname>", methods=["GET"])
@require_api_key
def download_backup(fname):
    p = os.path.join(BACKUPS_DIR, fname)
    if not os.path.exists(p):
        return jsonify({"error":"no encontrado"}), 404
    return send_file(p, as_attachment=True)

# -------------------------
# Flask runner in thread
# -------------------------
def run_flask_app():
    import logging
    log("Iniciando hilo del servidor Flask")
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    try:
        app.run(host=HOST, port=PORT, threaded=True, use_reloader=False)
    except Exception as e:
        log(f"Flask error al iniciar: {e}")

# -------------------------
# GUI (Tkinter)
# -------------------------
class ServerGUI:
    def __init__(self, root):
        self.root = root
        root.title("Gestor de Inventario Repuestos — Servidor")
        # modern-ish look: sizes and colors
        self.bg = "#f3f6f9"
        self.header_bg = "#2b73d8"
        self.header_fg = "#ffffff"
        root.configure(bg=self.bg)
        root.geometry("1024x700")
        root.minsize(900,600)

        self._build_header()
        self._build_main()
        self._refresh_gui_loop()

    def _build_header(self):
        header = tk.Frame(self.root, bg=self.header_bg, height=60)
        header.pack(fill="x")
        title = tk.Label(header, text="Gestor de Inventario Repuestos — Servidor", bg=self.header_bg, fg=self.header_fg, font=("Segoe UI", 14, "bold"))
        title.pack(side="left", padx=12, pady=10)
        sub = tk.Label(header, text=f"IP: {get_local_ip()}  |  Puerto: {PORT}", bg=self.header_bg, fg=self.header_fg, font=("Segoe UI", 10))
        sub.pack(side="right", padx=12)

    def _build_main(self):
        main = tk.Frame(self.root, bg=self.bg)
        main.pack(fill="both", expand=True, padx=10, pady=10)

        left = tk.Frame(main, bg=self.bg)
        left.pack(side="left", fill="both", expand=True)

        right = tk.Frame(main, bg=self.bg, width=320)
        right.pack(side="right", fill="y")

        # Left: logs text
        lbl_logs = tk.Label(left, text="Eventos recientes", bg=self.bg, font=("Segoe UI", 11, "bold"))
        lbl_logs.pack(anchor="w")
        self.log_text = tk.Text(left, height=25, state="disabled", bg="#ffffff")
        self.log_text.pack(fill="both", expand=True, padx=4, pady=6)

        # controls under logs
        ctrl_frame = tk.Frame(left, bg=self.bg)
        ctrl_frame.pack(fill="x", pady=6)
        tk.Button(ctrl_frame, text="Vaciar logs", command=self.clear_logs, width=12).pack(side="left", padx=4)
        tk.Button(ctrl_frame, text="Exportar logs", command=self.export_logs, width=12).pack(side="left", padx=4)
        tk.Button(ctrl_frame, text="Forzar backup", command=self.force_backup, width=12).pack(side="left", padx=4)
        tk.Button(ctrl_frame, text="Restaurar copia", command=self.restore_backup_dialog, width=14).pack(side="left", padx=4)

        # Right: status and clients
        status_lbl = tk.Label(right, text="Estado del Servidor", bg=self.bg, font=("Segoe UI", 11, "bold"))
        status_lbl.pack(anchor="w", pady=(0,4))
        self.status_text = tk.Label(right, text="", bg=self.bg, anchor="w", justify="left", font=("Segoe UI",10))
        self.status_text.pack(fill="x")

        clients_lbl = tk.Label(right, text="Clientes (último ping)", bg=self.bg, font=("Segoe UI", 11, "bold"))
        clients_lbl.pack(anchor="w", pady=(12,4))
        self.clients_list = tk.Listbox(right, height=8)
        self.clients_list.pack(fill="x", pady=4)

        # API key controls
        api_frame = tk.Frame(right, bg=self.bg)
        api_frame.pack(fill="x", pady=(12,4))
        tk.Button(api_frame, text="Crear/Ver API Key", command=self.show_api_key_dialog, width=18).pack(side="left", padx=4)
        tk.Button(api_frame, text="Cambiar API Key", command=self.change_api_key_dialog, width=14).pack(side="left", padx=4)

        # bottom controls
        bottom = tk.Frame(right, bg=self.bg)
        bottom.pack(fill="both", expand=True, pady=(12,0))
        tk.Button(bottom, text="Exportar DB", command=self.export_db_file, width=24).pack(pady=6)
        tk.Button(bottom, text="Salir", command=self.on_exit, width=24).pack(pady=6)

    def _refresh_gui_loop(self):
        # update logs (last N)
        with LOG_LOCK:
            text = "\n".join(LOG_LINES[-GUI_MAX_LOG_LINES:])
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.insert(tk.END, text)
        self.log_text.config(state="disabled")

        # update status
        try:
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM repuestos WHERE deleted=0")
            total = c.fetchone()[0]
            conn.close()
        except Exception:
            total = "?"
        status = f"Items activos: {total}\nÚltima actualización: {get_last_update()}\nHora local: {now_ts()}"
        self.status_text.config(text=status)

        # update clients
        self.clients_list.delete(0, tk.END)
        snap = get_clients_snapshot()
        for s in sorted(snap, key=lambda x: x["seconds_ago"]):
            self.clients_list.insert(tk.END, f"{s['client_id']} - {s['seconds_ago']}s")

        self.root.after(1500, self._refresh_gui_loop)

    # GUI actions
    def show_api_key_dialog(self):
        existing = read_api_key()
        if existing:
            if messagebox.askyesno("API Key existe", "¿Deseas ver la clave actual (se mostrará en texto)?"):
                messagebox.showinfo("API Key", f"La clave actual es:\n{existing}")
        else:
            new = simpledialog.askstring("Crear API Key", "No hay API Key. Introduce la nueva clave:", show="*")
            if new:
                write_api_key(new)
                log("API key creada desde GUI")
                messagebox.showinfo("API Key creada", "API key guardada en el servidor.")

    def change_api_key_dialog(self):
        existing = read_api_key()
        if not existing:
            messagebox.showwarning("Sin clave", "No existe clave actual. Usa 'Crear/Ver API Key' para crearla.")
            return
        old = simpledialog.askstring("Clave actual", "Introduce la clave actual:", show="*")
        if old is None:
            return
        if old != existing:
            messagebox.showerror("Incorrecto", "La clave actual no coincide.")
            return
        new = simpledialog.askstring("Nueva clave", "Introduce la nueva clave:", show="*")
        if not new:
            return
        write_api_key(new)
        log("API key actualizada desde GUI")
        messagebox.showinfo("Hecho", "API key actualizada correctamente.")

    def clear_logs(self):
        global LOG_LINES
        with LOG_LOCK:
            LOG_LINES = []
        try:
            open(LOG_FILE, "w", encoding="utf-8").close()
        except Exception:
            pass
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state="disabled")
        log("Logs vaciados manualmente")

    def export_logs(self):
        dest = filedialog.asksaveasfilename(title="Guardar logs como...", defaultextension=".txt", filetypes=[("Text files","*.txt"),("All","*.*")])
        if not dest:
            return
        try:
            shutil.copyfile(LOG_FILE, dest)
            messagebox.showinfo("Exportado", f"Logs exportados a {dest}")
            log(f"Logs exportados a {dest}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            log(f"Error exportar logs: {e}")

    def force_backup(self):
        try:
            if not os.path.exists(BACKUPS_DIR):
                os.makedirs(BACKUPS_DIR, exist_ok=True)
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            dest = os.path.join(BACKUPS_DIR, f"backup_{timestamp}.db")
            src = db.export_db_path()
            with DB_LOCK:
                db.conn.commit()
                db.conn.close()
                shutil.copyfile(src, dest)
                db._connect()
            log(f"Backup manual creado: {dest}")
            messagebox.showinfo("Backup", f"Copia creada: {dest}")
        except Exception as e:
            log(f"Backup manual error: {e}")
            messagebox.showerror("Error", str(e))

    def restore_backup_dialog(self):
        if not os.path.exists(BACKUPS_DIR):
            messagebox.showinfo("Restaurar", "No hay copias de seguridad.")
            return
        files = sorted(os.listdir(BACKUPS_DIR), reverse=True)
        if not files:
            messagebox.showinfo("Restaurar", "No hay copias de seguridad.")
            return
        msg = "Copias disponibles:\n" + "\n".join(files) + "\n\nIntroduce el nombre del archivo a restaurar (exacto):"
        sel = simpledialog.askstring("Restaurar copia", msg)
        if not sel:
            return
        p = os.path.join(BACKUPS_DIR, sel)
        if not os.path.exists(p):
            messagebox.showerror("No existe", "Archivo no encontrado.")
            return
        if not messagebox.askyesno("Confirmar restauración", f"Se creará una copia previa y se restaurará {sel}. ¿Continuar?"):
            return
        try:
            # create pre-restore copy
            src = db.export_db_path()
            pre = os.path.join(BACKUPS_DIR, f"pre_restore_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.db")
            with DB_LOCK:
                db.conn.commit()
                db.conn.close()
                shutil.copyfile(src, pre)
                # replace
                shutil.copyfile(p, src)
                # reconnect DB
                db._connect()
            update_last_update()
            log(f"Restauración ejecutada desde {sel}. Pre-restore guardado en {pre}")
            messagebox.showinfo("Restaurado", "Restauración completada. DB reemplazada.")
        except Exception as e:
            log(f"Error restaurando copia: {e}")
            messagebox.showerror("Error", str(e))

    def export_db_file(self):
        src = db.export_db_path()
        dest = filedialog.asksaveasfilename(title="Exportar DB como...", defaultextension=".db", filetypes=[("SQLite DB","*.db"),("All","*.*")])
        if not dest:
            return
        try:
            with DB_LOCK:
                db.conn.commit()
                shutil.copyfile(src, dest)
            messagebox.showinfo("Exportado", f"DB exportada a {dest}")
            log(f"DB exportada a {dest}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            log(f"Export error: {e}")

    def on_exit(self):
        if messagebox.askyesno("Salir", "¿Deseas detener el servidor y salir?"):
            log("Servidor detenido desde GUI")
            try:
                os._exit(0)
            except Exception:
                self.root.quit()

# -------------------------
# Startup: backup diario y GUI start
# -------------------------
def auto_backup_on_start():
    # create backup on start (daily)
    try:
        if not os.path.exists(BACKUPS_DIR):
            os.makedirs(BACKUPS_DIR, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        dest = os.path.join(BACKUPS_DIR, f"backup_{timestamp}.db")
        src = db.export_db_path()
        with DB_LOCK:
            db.conn.commit()
            db.conn.close()
            shutil.copyfile(src, dest)
            db._connect()
        log(f"Backup diario creado: {dest}")
    except Exception as e:
        log(f"Error backup diario: {e}")

def ensure_api_key_on_start(root):
    existing = read_api_key()
    if existing is None:
        messagebox.showinfo("API Key", "No se ha detectado una API key en el servidor. Debes crearla ahora.")
        new = simpledialog.askstring("Crear API Key", "Introduce la nueva clave para el servidor:", show="*")
        if new:
            write_api_key(new)
            log("API key creada inicialmente desde GUI")
            messagebox.showinfo("Hecho", "API key creada y guardada en api_key.txt")
        else:
            messagebox.showwarning("Atención", "No se creó API key. El servidor rechazará peticiones protegidas hasta crearla.")

def start_gui_and_server():
    # start flask thread
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()

    # start GUI
    root = tk.Tk()
    gui = ServerGUI(root)

    # ensure API key
    root.after(300, lambda: ensure_api_key_on_start(root))

    # auto backup at start (in a separate thread so GUI isn't blocked)
    threading.Thread(target=auto_backup_on_start, daemon=True).start()

    root.protocol("WM_DELETE_WINDOW", gui.on_exit)
    root.mainloop()

# -------------------------
# Main
# -------------------------
def main():
    log("Iniciando servidor (GUI + API)...")
    start_gui_and_server()

if __name__ == "__main__":
    main()
