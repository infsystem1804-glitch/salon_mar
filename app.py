from datetime import datetime
import sqlite3
from flask import Flask, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = "clave_super_secreta_salon"  # Cambia esto en producción
PIN_ADMIN = "1234"  # PIN de acceso para el personal
WHATSAPP_SALON = "525512345678"  # Número del salón con código de país


def get_db():
    conn = sqlite3.connect("salon.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    # Tabla de Citas
    c.execute("""CREATE TABLE IF NOT EXISTS citas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente TEXT NOT NULL,
        telefono TEXT NOT NULL,
        servicio TEXT NOT NULL,
        precio REAL NOT NULL,
        fecha TEXT NOT NULL,
        hora TEXT NOT NULL,
        estado TEXT DEFAULT 'Confirmada' -- Confirmada, Completada, Cancelada
    )""")
    # Tabla de Insumos
    c.execute("""CREATE TABLE IF NOT EXISTS insumos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto TEXT NOT NULL,
        cantidad INTEGER NOT NULL,
        minimo INTEGER NOT NULL
    )""")
    # Tabla de Caja (Ingresos y Egresos)
    c.execute("""CREATE TABLE IF NOT EXISTS caja (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT NOT NULL, -- Ingreso o Egreso
        concepto TEXT NOT NULL,
        monto REAL NOT NULL,
        fecha TEXT NOT NULL
    )""")
    conn.commit()
    conn.close()


# Catálogo de servicios y horarios base
SERVICIOS = {
    "Uñas Acrílicas Set Completo": 450,
    "Gelish": 220,
    "Manicure": 300,
    "Retoque de Acrílico": 280,
    "Pedicure Spa": 350,
}
HORARIOS_BASE = ["10:00", "11:30", "13:00", "15:00", "16:30", "18:00"]


# --- RUTA PÚBLICA (CLIENTAS) ---
@app.route("/", methods=["GET", "POST"])
def index():
    conn = get_db()
    fecha_seleccionada = request.args.get(
        "fecha", datetime.now().strftime("%Y-%m-%d")
    )

    if request.method == "POST":
        cliente = request.form["cliente"]
        telefono = request.form["telefono"]
        servicio = request.form["servicio"]
        precio = SERVICIOS.get(servicio, 0)
        fecha = request.form["fecha"]
        hora = request.form["hora"]

        conn.execute(
            "INSERT INTO citas (cliente, telefono, servicio, precio, fecha, hora) VALUES (?, ?, ?, ?, ?, ?)",
            (cliente, telefono, servicio, precio, fecha, hora),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("index", fecha=fecha, exito=1))

    # Consultar citas de la fecha seleccionada
    citas_dia = conn.execute(
        "SELECT hora, estado FROM citas WHERE fecha = ?", (fecha_seleccionada,)
    ).fetchall()
    conn.close()

    ocupados = [c["hora"] for c in citas_dia if c["estado"] != "Cancelada"]
    liberados = [
        c["hora"]
        for c in citas_dia
        if c["estado"] == "Cancelada" and c["hora"] not in ocupados
    ]

    disponibles = []
    for h in HORARIOS_BASE:
        if h not in ocupados:
            disponibles.append({"hora": h, "liberado": h in liberados})

    return render_template(
        "index.html",
        servicios=SERVICIOS,
        disponibles=disponibles,
        fecha=fecha_seleccionada,
        whatsapp=WHATSAPP_SALON,
        exito=request.args.get("exito"),
    )


# --- LOGIN PERSONAL ---
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form["pin"] == PIN_ADMIN:
            session["admin"] = True
            return redirect(url_for("admin"))
        error = "PIN incorrecto"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("index"))


# --- PANEL PRIVADO (ADMINISTRACIÓN) ---
@app.route("/admin")
def admin():
    if not session.get("admin"):
        return redirect(url_for("login"))

    conn = get_db()
    citas = conn.execute(
        "SELECT * FROM citas ORDER BY fecha DESC, hora ASC"
    ).fetchall()
    insumos = conn.execute("SELECT * FROM insumos").fetchall()
    movimientos = conn.execute(
        "SELECT * FROM caja ORDER BY id DESC LIMIT 15"
    ).fetchall()

    ingresos = (
        conn.execute(
            "SELECT SUM(monto) FROM caja WHERE tipo='Ingreso'"
        ).fetchone()[0]
        or 0
    )
    egresos = (
        conn.execute(
            "SELECT SUM(monto) FROM caja WHERE tipo='Egreso'"
        ).fetchone()[0]
        or 0
    )
    conn.close()

    return render_template(
        "admin.html",
        citas=citas,
        insumos=insumos,
        movimientos=movimientos,
        ingresos=ingresos,
        egresos=egresos,
        balance=ingresos - egresos,
    )


# --- ACCIONES DE ADMINISTRACIÓN ---
@app.route("/cita/<int:id>/<accion>")
def accion_cita(id, accion):
    if not session.get("admin"):
        return redirect(url_for("login"))
    conn = get_db()
    cita = conn.execute("SELECT * FROM citas WHERE id = ?", (id,)).fetchone()
    if cita:
        if accion == "completar" and cita["estado"] != "Completada":
            conn.execute(
                "UPDATE citas SET estado = 'Completada' WHERE id = ?", (id,)
            )
            conn.execute(
                "INSERT INTO caja (tipo, concepto, monto, fecha) VALUES ('Ingreso', ?, ?, ?)",
                (
                    f"Cita: {cita['cliente']} ({cita['servicio']})",
                    cita["precio"],
                    cita["fecha"],
                ),
            )
        elif accion == "cancelar":
            conn.execute(
                "UPDATE citas SET estado = 'Cancelada' WHERE id = ?", (id,)
            )
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/insumo/agregar", methods=["POST"])
def agregar_insumo():
    if not session.get("admin"):
        return redirect(url_for("login"))
    conn = get_db()
    conn.execute(
        "INSERT INTO insumos (producto, cantidad, minimo) VALUES (?, ?, ?)",
        (
            request.form["producto"],
            int(request.form["cantidad"]),
            int(request.form["minimo"]),
        ),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/insumo/<int:id>/<op>")
def actualizar_insumo(id, op):
    if not session.get("admin"):
        return redirect(url_for("login"))
    conn = get_db()
    delta = 1 if op == "sumar" else -1
    conn.execute(
        "UPDATE insumos SET cantidad = MAX(0, cantidad + ?) WHERE id = ?",
        (delta, id),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/gasto/agregar", methods=["POST"])
def agregar_gasto():
    if not session.get("admin"):
        return redirect(url_for("login"))
    conn = get_db()
    conn.execute(
        "INSERT INTO caja (tipo, concepto, monto, fecha) VALUES ('Egreso', ?, ?, ?)",
        (
            request.form["concepto"],
            float(request.form["monto"]),
            datetime.now().strftime("%Y-%m-%d"),
        ),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))
init_db()

if __name__ == "__main__":
    
    app.run(debug=True)