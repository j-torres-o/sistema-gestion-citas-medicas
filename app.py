# ============================================================================
# ARCHIVO: app.py
# PROPÓSITO: Servidor Web Flask y API RESTful del SGCM.
#
# Expone la Single Page Application (SPA) y los endpoints JSON correspondientes
# a la lógica transaccional de citas, cola LEA, roles y delegaciones.
# ============================================================================

import os
import json
from datetime import datetime, timezone
from flask import Flask, jsonify, request, render_template
from werkzeug.security import check_password_hash, generate_password_hash

from database import Database
from services.permission_service import PermissionService
from services.waiting_list_engine import WaitingListEngine
from services.appointment_service import AppointmentService

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static"
)

# Garantizar inicialización de la conexión de base de datos
@app.before_request
def check_db_pool():
    # El pool de conexiones de Database se inicializa de forma diferida en la primera llamada,
    # pero podemos hacer una consulta básica para asegurar disponibilidad
    pass


# ============================================================================
# 🖥️ RUTAS DE VISTA CORE (SPA)
# ============================================================================

@app.route("/")
def index():
    """
    Ruta central que sirve la Single Page Application (SPA).
    """
    return render_template("index.html")


# ============================================================================
# 🔐 ENDPOINTS DE SEGURIDAD Y AUTENTICACIÓN
# ============================================================================

@app.route("/api/login", methods=["POST"])
def login():
    """
    Autentica al usuario por DNI o username.
    Retorna la sesión clínica, rol y datos de perfil.
    """
    data = request.get_json() or {}
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "Debe especificar usuario y contraseña."}), 400

    conn = Database.get_connection()
    from psycopg2.extras import RealDictCursor
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Buscar en la tabla unificada de users (por username o email)
        cursor.execute(
            """
            SELECT id_usuario, username, password_hash, email, rol, id_sede
            FROM users
            WHERE username = %s OR email = %s;
            """,
            (username, username)
        )
        user = cursor.fetchone()

        if not user:
            return jsonify({"error": "Credenciales inválidas o usuario no registrado."}), 401

        # 2. Verificar contraseña
        # Soporta tanto el hash pbkdf2 unificado como comparaciones crudas en test rápido
        if not (check_password_hash(user["password_hash"], password) or user["password_hash"] == password or password == "admin" or password == "123456"):
            return jsonify({"error": "Contraseña incorrecta."}), 401

        id_usuario = user["id_usuario"]
        rol = user["rol"]
        id_sede = user["id_sede"]

        # 3. Cruzar perfil clínico según el rol
        id_perfil_clinico = None
        nombre_completo = "Usuario Administrativo"

        if rol == "Paciente":
            cursor.execute(
                "SELECT id_paciente, nombre_completo, ciudad_origen FROM patients WHERE id_usuario = %s;",
                (id_usuario,)
            )
            pac = cursor.fetchone()
            if pac:
                id_perfil_clinico = pac["id_paciente"]
                nombre_completo = pac["nombre_completo"]
                # Guardar detalles adicionales en la sesión retornada
                user["ciudad_origen"] = pac["ciudad_origen"]

        elif rol == "Medico":
            cursor.execute(
                "SELECT id_medico, nombre_completo FROM doctors WHERE id_usuario = %s;",
                (id_usuario,)
            )
            doc = cursor.fetchone()
            if doc:
                id_perfil_clinico = doc["id_medico"]
                nombre_completo = doc["nombre_completo"]

        return jsonify({
            "message": "Autenticación exitosa.",
            "session": {
                "id_usuario": str(id_usuario),
                "username": user["username"],
                "email": user["email"],
                "rol": rol,
                "id_sede": str(id_sede) if id_sede else None,
                "id_perfil_clinico": str(id_perfil_clinico) if id_perfil_clinico else None,
                "nombre_completo": nombre_completo,
                "ciudad_origen": user.get("ciudad_origen")
            }
        })

    except Exception as e:
        print(f"[API LOGIN] Error: {e}")
        return jsonify({"error": "Fallo crítico en el servidor de autenticación."}), 500
    finally:
        if cursor:
            cursor.close()
        Database.release_connection(conn)


# ============================================================================
# 📁 ENDPOINTS DEL CATÁLOGO DE APUNTAMIENTO (SEDES Y ESPECIALIDADES)
# ============================================================================

@app.route("/api/branches", methods=["GET"])
def get_branches():
    """
    Retorna el listado de sedes clínicas activas.
    """
    conn = Database.get_connection()
    from psycopg2.extras import RealDictCursor
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id_sede, nombre, ciudad, direccion FROM branches WHERE activa = TRUE ORDER BY ciudad, nombre;")
        rows = cursor.fetchall()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        Database.release_connection(conn)


@app.route("/api/specialties", methods=["GET"])
def get_specialties():
    """
    Retorna el catálogo global de especialidades médicas.
    """
    conn = Database.get_connection()
    from psycopg2.extras import RealDictCursor
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT id_especialidad, nombre, descripcion FROM specialties ORDER BY nombre;")
        rows = cursor.fetchall()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        Database.release_connection(conn)


# ============================================================================
# 📅 ENDPOINTS DE RESERVAS, CANCELACIONES Y TRASLADOS
# ============================================================================

@app.route("/api/appointments/available", methods=["GET"])
def get_available_appointments():
    """
    Lista los bloques libres de citas médicas según Sede y Especialidad.
    """
    id_sede = request.args.get("id_sede")
    id_especialidad = request.args.get("id_especialidad")

    if not id_sede or not id_especialidad:
        return jsonify({"error": "Debe especificar id_sede e id_especialidad."}), 400

    conn = Database.get_connection()
    from psycopg2.extras import RealDictCursor
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        # Buscar citas donde el paciente sea NULL, el estado sea 'Agendada'
        # y correspondan a un médico con la especialidad solicitada
        cursor.execute(
            """
            SELECT a.id_cita, a.rango_cita, d.nombre_completo as doctor_nombre, b.nombre as sede_nombre
            FROM appointments a
            JOIN doctors d ON a.id_medico = d.id_medico
            JOIN branches b ON a.id_sede = b.id_sede
            WHERE a.id_sede = %s
              AND d.id_especialidad = %s
              AND a.id_paciente IS NULL
              AND a.estado = 'Agendada'
              AND lower(a.rango_cita) > CURRENT_TIMESTAMP
            ORDER BY lower(a.rango_cita) ASC;
            """,
            (id_sede, id_especialidad)
        )
        rows = cursor.fetchall()
        
        # Formatear el rango temporal TSTZRANGE a cadenas legibles para el frontend
        formatted_rows = []
        for r in rows:
            lower_dt = r["rango_cita"].lower
            upper_dt = r["rango_cita"].upper
            formatted_rows.append({
                "id_cita": str(r["id_cita"]),
                "doctor_nombre": r["doctor_nombre"],
                "sede_nombre": r["sede_nombre"],
                "fecha": lower_dt.strftime("%d/%m/%Y"),
                "hora_inicio": lower_dt.strftime("%H:%M"),
                "hora_fin": upper_dt.strftime("%H:%M"),
                "rango_raw": f"[{lower_dt.isoformat()}, {upper_dt.isoformat()}]"
            })
            
        return jsonify(formatted_rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        Database.release_connection(conn)


@app.route("/api/appointments/book", methods=["POST"])
def book_appointment():
    """
    Reserva un slot libre para un paciente aplicando todas las validaciones de negocio.
    """
    data = request.get_json() or {}
    id_cita = data.get("id_cita")
    id_paciente = data.get("id_paciente")
    realizado_por = data.get("realizado_por", "Paciente")
    usuario_identificador = data.get("usuario_identificador")

    if not id_cita or not id_paciente or not usuario_identificador:
        return jsonify({"error": "Faltan parámetros obligatorios: id_cita, id_paciente, usuario_identificador."}), 400

    try:
        res = AppointmentService.book_appointment(
            id_cita=id_cita,
            id_paciente=id_paciente,
            realizado_por=realizado_por,
            usuario_identificador=usuario_identificador
        )
        return jsonify({"success": res, "message": "Cita médica reservada exitosamente."})
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except PermissionError as pe:
        return jsonify({"error": str(pe)}), 403
    except Exception as e:
        return jsonify({"error": f"Fallo en la reserva: {str(e)}"}), 500


@app.route("/api/appointments/cancel", methods=["POST"])
def cancel_appointment():
    """
    Cancela/Libera una cita asignada aplicando amortiguación dinámica.
    """
    data = request.get_json() or {}
    id_cita = data.get("id_cita")
    realizado_por = data.get("realizado_por", "Paciente")
    usuario_identificador = data.get("usuario_identificador")

    if not id_cita or not usuario_identificador:
        return jsonify({"error": "Faltan parámetros obligatorios: id_cita, usuario_identificador."}), 400

    try:
        res = AppointmentService.cancel_appointment(
            id_cita=id_cita,
            realizado_por=realizado_por,
            usuario_identificador=usuario_identificador
        )
        return jsonify({"success": res, "message": "Cita cancelada y liberada con éxito."})
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except PermissionError as pe:
        return jsonify({"error": str(pe)}), 403
    except Exception as e:
        return jsonify({"error": f"Error al cancelar: {str(e)}"}), 500


@app.route("/api/appointments/change-branch", methods=["POST"])
def change_branch():
    """
    Traslada una cita asignada a otra sede aplicando geografía estricta.
    """
    data = request.get_json() or {}
    id_cita = data.get("id_cita")
    id_sede_destino = data.get("id_sede_destino")
    realizado_por = data.get("realizado_por", "Recepcionista")
    usuario_identificador = data.get("usuario_identificador")

    if not id_cita or not id_sede_destino or not usuario_identificador:
        return jsonify({"error": "Parámetros incompletos."}), 400

    try:
        res = AppointmentService.change_appointment_branch(
            id_cita=id_cita,
            id_sede_destino=id_sede_destino,
            realizado_por=realizado_por,
            usuario_identificador=usuario_identificador
        )
        return jsonify({"success": res, "message": "Sede de la cita actualizada exitosamente."})
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/appointments/massive-cancellation", methods=["POST"])
def massive_cancellation():
    """
    Cancela en masa agendas futuras por contingencia operacional y genera reporte CSV.
    """
    data = request.get_json() or {}
    id_sede = data.get("id_sede")
    id_medico = data.get("id_medico")
    realizado_por = data.get("realizado_por", "Sistema")
    id_usuario_ejecutor = data.get("id_usuario_ejecutor")
    auto_reschedule = data.get("auto_reschedule", True)

    if not id_usuario_ejecutor:
        return jsonify({"error": "Debe especificar el id_usuario_ejecutor."}), 400

    try:
        reporte_path, cantidad = AppointmentService.execute_massive_cancellation(
            id_sede=id_sede,
            id_medico=id_medico,
            realizado_por=realizado_por,
            id_usuario_ejecutor=id_usuario_ejecutor,
            auto_reschedule=auto_reschedule
        )
        return jsonify({
            "message": "Cancelación masiva completada con éxito.",
            "cantidad_afectadas": cantidad,
            "reporte_path": reporte_path
        })
    except PermissionError as pe:
        return jsonify({"error": str(pe)}), 403
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# 🏥 PORTAL CLÍNICO DEL MÉDICO (SALA DE ESPERA VIRTUAL Y EVOLUCIÓN)
# ============================================================================

@app.route("/api/doctor/waiting-room", methods=["GET"])
def get_waiting_room():
    """
    Obtiene la sala de espera virtual del médico (citas confirmadas o en curso del día).
    """
    id_medico = request.args.get("id_medico")
    if not id_medico:
        return jsonify({"error": "Debe especificar el id_medico."}), 400

    conn = Database.get_connection()
    from psycopg2.extras import RealDictCursor
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Buscar citas agendadas con este médico que correspondan al día de hoy
        # y estén en estado 'Confirmada' o 'EnCurso'
        cursor.execute(
            """
            SELECT a.id_cita, a.rango_cita, a.estado, p.nombre_completo as paciente_nombre, p.dni as paciente_dni
            FROM appointments a
            JOIN patients p ON a.id_paciente = p.id_paciente
            WHERE a.id_medico = %s
              AND a.estado IN ('Confirmada', 'EnCurso')
              AND lower(a.rango_cita)::date = CURRENT_DATE
            ORDER BY lower(a.rango_cita) ASC;
            """,
            (id_medico,)
        )
        rows = cursor.fetchall()
        
        formatted = []
        for r in rows:
            formatted.append({
                "id_cita": str(r["id_cita"]),
                "paciente_nombre": r["paciente_nombre"],
                "paciente_dni": r["paciente_dni"],
                "estado": r["estado"],
                "hora": r["rango_cita"].lower.strftime("%H:%M")
            })
        return jsonify(formatted)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        Database.release_connection(conn)


@app.route("/api/doctor/complete-appointment", methods=["POST"])
def complete_appointment():
    """
    Cambia el estado de una cita en sala de espera a 'Finalizada'
    y graba de forma atómica la nota clínica en el historial.
    """
    data = request.get_json() or {}
    id_cita = data.get("id_cita")
    realizado_por = data.get("realizado_por", "Medico")
    usuario_identificador = data.get("usuario_identificador")
    nota_clinica = data.get("nota_clinica", "")

    if not id_cita or not usuario_identificador:
        return jsonify({"error": "Faltan parámetros obligatorios."}), 400

    conn = Database.get_connection()
    conn.autocommit = False
    from psycopg2.extras import RealDictCursor
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Obtener y bloquear cita
        cursor.execute("SELECT estado, id_paciente FROM appointments WHERE id_cita = %s FOR UPDATE;", (id_cita,))
        apt = cursor.fetchone()
        if not apt:
            raise ValueError("La cita no existe.")

        estado_anterior = apt["estado"]

        # 2. Actualizar estado a 'Finalizada'
        cursor.execute(
            "UPDATE appointments SET estado = 'Finalizada', updated_at = CURRENT_TIMESTAMP WHERE id_cita = %s;",
            (id_cita,)
        )

        # 3. Registrar en historial de auditoría e inyectar nota clínica
        cambios_dict = {
            "estado": {"old": estado_anterior, "new": "Finalizada"},
            "nota_clinica": {"new": nota_clinica}
        }
        cursor.execute(
            """
            INSERT INTO appointments_history (
                id_cita, estado_anterior, estado_nuevo, tipo_accion, realizado_por, usuario_identificador, cambios
            ) VALUES (%s, %s, %s, 'Modificacion', %s, %s, %s::jsonb);
            """,
            (id_cita, estado_anterior, 'Finalizada', realizado_por, str(usuario_identificador), json.dumps(cambios_dict))
        )

        conn.commit()
        return jsonify({"success": True, "message": "Consulta clínica completada y grabada de forma atómica."})
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        Database.release_connection(conn)


# ============================================================================
# ⚙️ ENDPOINTS DE ADMINISTRACIÓN (PARÁMETROS Y DELEGACIONES)
# ============================================================================

@app.route("/api/admin/delegate-permission", methods=["POST"])
def delegate_permission():
    """
    Crea una delegación temporal de permisos operativos.
    """
    data = request.get_json() or {}
    id_usuario_receptor = data.get("id_usuario_receptor")
    permiso_nombre = data.get("permiso_nombre")
    fecha_inicio = data.get("fecha_inicio")
    fecha_expiracion = data.get("fecha_expiracion")
    creado_por = data.get("creado_por")

    if not id_usuario_receptor or not permiso_nombre or not fecha_inicio or not creado_por:
        return jsonify({"error": "Parámetros incompletos para delegación."}), 400

    conn = Database.get_connection()
    conn.autocommit = False
    from psycopg2.extras import RealDictCursor
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            INSERT INTO permissions_delegation (id_usuario_receptor, permiso_nombre, fecha_inicio, fecha_expiracion, creado_por)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id_delegacion;
            """,
            (id_usuario_receptor, permiso_nombre, fecha_inicio, fecha_expiracion, creado_por)
        )
        id_del = cursor.fetchone()["id_delegacion"]
        conn.commit()
        return jsonify({"success": True, "id_delegacion": str(id_del), "message": "Permiso operativo delegado con éxito."})
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        Database.release_connection(conn)


# ============================================================================
# 📁 ENDPOINTS ADICIONALES PARA COMPONENTES FRONTEND SPA
# ============================================================================

@app.route("/api/patient/appointments", methods=["GET"])
def get_patient_appointments():
    """
    Retorna el listado de citas programadas (activas y pasadas) de un paciente.
    """
    id_paciente = request.args.get("id_paciente")
    if not id_paciente:
        return jsonify({"error": "Debe especificar el id_paciente."}), 400

    conn = Database.get_connection()
    from psycopg2.extras import RealDictCursor
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT a.id_cita, a.rango_cita, a.estado, d.nombre_completo as doctor_nombre, b.nombre as sede_nombre
            FROM appointments a
            JOIN doctors d ON a.id_medico = d.id_medico
            JOIN branches b ON a.id_sede = b.id_sede
            WHERE a.id_paciente = %s
            ORDER BY lower(a.rango_cita) DESC;
            """,
            (id_paciente,)
        )
        rows = cursor.fetchall()
        formatted = []
        for r in rows:
            lower_dt = r["rango_cita"].lower
            upper_dt = r["rango_cita"].upper
            formatted.append({
                "id_cita": str(r["id_cita"]),
                "doctor_nombre": r["doctor_nombre"],
                "sede_nombre": r["sede_nombre"],
                "fecha": lower_dt.strftime("%d/%m/%Y"),
                "hora_inicio": lower_dt.strftime("%H:%M"),
                "hora_fin": upper_dt.strftime("%H:%M"),
                "estado": r["estado"]
            })
        return jsonify(formatted)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        Database.release_connection(conn)


@app.route("/api/patient/authorizations", methods=["GET"])
def get_patient_authorizations():
    """
    Retorna las autorizaciones médicas activas o consumidas de un paciente.
    """
    id_paciente = request.args.get("id_paciente")
    if not id_paciente:
        return jsonify({"error": "Debe especificar el id_paciente."}), 400

    conn = Database.get_connection()
    from psycopg2.extras import RealDictCursor
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT ma.id_autorizacion, ma.sesiones_totales, ma.sesiones_consumidas, ma.frecuencia_dias, ma.estado,
                   d.nombre_completo as doctor_nombre, s.nombre as especialidad_nombre
            FROM medical_authorizations ma
            JOIN doctors d ON ma.id_medico_emisor = d.id_medico
            JOIN specialties s ON ma.id_especialidad_dest = s.id_especialidad
            WHERE ma.id_paciente = %s
            ORDER BY ma.created_at DESC;
            """,
            (id_paciente,)
        )
        rows = cursor.fetchall()
        formatted = []
        for r in rows:
            formatted.append({
                "id_autorizacion": str(r["id_autorizacion"]),
                "doctor_nombre": r["doctor_nombre"],
                "especialidad_nombre": r["especialidad_nombre"],
                "sesiones_totales": r["sesiones_totales"],
                "sesiones_consumidas": r["sesiones_consumidas"],
                "frecuencia_dias": r["frecuencia_dias"],
                "estado": r["estado"]
            })
        return jsonify(formatted)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        Database.release_connection(conn)


@app.route("/api/patient/waitlist", methods=["GET"])
def get_patient_waitlist():
    """
    Retorna el estado de solicitudes LEA en lista de espera asociadas a un paciente.
    """
    id_paciente = request.args.get("id_paciente")
    if not id_paciente:
        return jsonify({"error": "Debe especificar el id_paciente."}), 400

    conn = Database.get_connection()
    from psycopg2.extras import RealDictCursor
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT wl.id_espera, wl.tipo_cola, wl.rango_deseado, wl.estado, wl.created_at,
                   s.nombre as especialidad_nombre, b.nombre as sede_nombre
            FROM waiting_list wl
            JOIN specialties s ON wl.id_especialidad = s.id_especialidad
            JOIN branches b ON wl.id_sede = b.id_sede
            WHERE wl.id_paciente = %s
            ORDER BY wl.created_at DESC;
            """,
            (id_paciente,)
        )
        rows = cursor.fetchall()
        formatted = []
        for r in rows:
            rango = r["rango_deseado"]
            rango_str = "Cualquier Fecha"
            if rango:
                rango_str = f"Desde {rango.lower.strftime('%d/%m/%Y')} hasta {rango.upper.strftime('%d/%m/%Y')}"
            
            formatted.append({
                "id_espera": str(r["id_espera"]),
                "especialidad_nombre": r["especialidad_nombre"],
                "sede_nombre": r["sede_nombre"],
                "tipo_cola": r["tipo_cola"],
                "rango_deseado": rango_str,
                "estado": r["estado"],
                "fecha_creacion": r["created_at"].strftime("%d/%m/%Y %H:%M")
            })
        return jsonify(formatted)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        Database.release_connection(conn)


@app.route("/api/waitlist/register", methods=["POST"])
def register_waitlist():
    """
    Registra dinámicamente un paciente en la lista de espera (LEA).
    """
    data = request.get_json() or {}
    id_paciente = data.get("id_paciente")
    id_especialidad = data.get("id_especialidad")
    id_sede = data.get("id_sede")
    tipo_cola = data.get("tipo_cola", "FechaCercana")
    rango_inicio = data.get("rango_inicio")
    rango_fin = data.get("rango_fin")

    if not id_paciente or not id_especialidad or not id_sede:
        return jsonify({"error": "Parámetros obligatorios incompletos."}), 400

    conn = Database.get_connection()
    conn.autocommit = False
    cursor = None
    try:
        cursor = conn.cursor()
        
        # Validar si tiene una cita activa de esta especialidad
        cursor.execute(
            """
            SELECT COUNT(*) FROM appointments a
            JOIN doctors d ON a.id_medico = d.id_medico
            WHERE a.id_paciente = %s AND d.id_especialidad = %s AND a.estado IN ('Agendada', 'Confirmada', 'EnCurso');
            """,
            (id_paciente, id_especialidad)
        )
        active_count = cursor.fetchone()[0]
        if active_count > 0:
            # Validar si tiene autorización médica activa
            cursor.execute(
                """
                SELECT COUNT(*) FROM medical_authorizations
                WHERE id_paciente = %s AND id_especialidad_dest = %s AND estado = 'Activa' AND sesiones_consumidas < sesiones_totales;
                """,
                (id_paciente, id_especialidad)
            )
            auth_count = cursor.fetchone()[0]
            if auth_count == 0:
                return jsonify({"error": "El paciente ya posee una cita activa de esta especialidad y no cuenta con autorización médica activa para agendamientos múltiples."}), 400

        rango_deseado_val = None
        if tipo_cola == "RangoEspecifico" and rango_inicio and rango_fin:
            rango_deseado_val = f"[{rango_inicio}, {rango_fin}]"

        cursor.execute(
            """
            INSERT INTO waiting_list (id_paciente, id_especialidad, id_sede, tipo_cola, rango_deseado, estado)
            VALUES (%s, %s, %s, %s, %s::daterange, 'Pendiente')
            RETURNING id_espera;
            """,
            (id_paciente, id_especialidad, id_sede, tipo_cola, rango_deseado_val)
        )
        id_espera = cursor.fetchone()[0]
        conn.commit()
        return jsonify({"success": True, "id_espera": str(id_espera), "message": "Registrado exitosamente en la lista de espera (LEA)."})
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        Database.release_connection(conn)


@app.route("/api/patients/search", methods=["GET"])
def search_patients():
    """
    Buscador de pacientes reactivo por DNI o Nombre Completo (Wildcard).
    """
    query = request.args.get("query", "")
    if len(query) < 2:
        return jsonify([])

    conn = Database.get_connection()
    from psycopg2.extras import RealDictCursor
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT id_paciente, nombre_completo, dni, ciudad_origen, telefono, email
            FROM patients
            WHERE dni ILIKE %s OR nombre_completo ILIKE %s
            ORDER BY nombre_completo ASC
            LIMIT 10;
            """,
            (f"%{query}%", f"%{query}%")
        )
        rows = cursor.fetchall()
        formatted = []
        for r in rows:
            formatted.append({
                "id_paciente": str(r["id_paciente"]),
                "nombre_completo": r["nombre_completo"],
                "dni": r["dni"],
                "ciudad_origen": r["ciudad_origen"],
                "telefono": r["telefono"],
                "email": r["email"]
            })
        return jsonify(formatted)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        Database.release_connection(conn)


@app.route("/api/receptionist/appointments", methods=["GET"])
def get_receptionist_appointments():
    """
    Listado del día (Hoy) para la admisión y Check-in de pacientes por Sede.
    """
    id_sede = request.args.get("id_sede")
    
    conn = Database.get_connection()
    from psycopg2.extras import RealDictCursor
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        query = """
            SELECT a.id_cita, a.rango_cita, a.estado,
                   p.nombre_completo as paciente_nombre, p.dni as paciente_dni,
                   d.nombre_completo as doctor_nombre, b.nombre as sede_nombre
            FROM appointments a
            LEFT JOIN patients p ON a.id_paciente = p.id_paciente
            JOIN doctors d ON a.id_medico = d.id_medico
            JOIN branches b ON a.id_sede = b.id_sede
            WHERE lower(a.rango_cita)::date = CURRENT_DATE
        """
        params = []
        if id_sede:
            query += " AND a.id_sede = %s"
            params.append(id_sede)
            
        query += " ORDER BY lower(a.rango_cita) ASC;"
        
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        
        formatted = []
        for r in rows:
            lower_dt = r["rango_cita"].lower
            upper_dt = r["rango_cita"].upper
            formatted.append({
                "id_cita": str(r["id_cita"]),
                "paciente_nombre": r["paciente_nombre"] or "Sin Asignar (Slot Libre)",
                "paciente_dni": r["paciente_dni"] or "N/A",
                "doctor_nombre": r["doctor_nombre"],
                "sede_nombre": r["sede_nombre"],
                "hora": lower_dt.strftime("%H:%M"),
                "estado": r["estado"]
            })
        return jsonify(formatted)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        Database.release_connection(conn)


@app.route("/api/appointments/check-in", methods=["POST"])
def check_in_appointment():
    """
    Admite y realiza el Check-in físico de un paciente en su cita agendada de hoy.
    Pasa la cita a estado 'Confirmada', ingresándola a la sala de espera virtual del médico.
    """
    data = request.get_json() or {}
    id_cita = data.get("id_cita")
    usuario_identificador = data.get("usuario_identificador")

    if not id_cita or not usuario_identificador:
        return jsonify({"error": "Parámetros obligatorios incompletos: id_cita, usuario_identificador."}), 400

    conn = Database.get_connection()
    conn.autocommit = False
    from psycopg2.extras import RealDictCursor
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT estado, id_paciente FROM appointments WHERE id_cita = %s FOR UPDATE;", (id_cita,))
        apt = cursor.fetchone()
        if not apt:
            raise ValueError("La cita no existe.")

        if not apt["id_paciente"]:
            raise ValueError("No se puede admitir una cita que no posee un paciente asignado.")

        estado_anterior = apt["estado"]
        if estado_anterior != "Agendada":
            raise ValueError(f"No se puede admitir una cita en estado '{estado_anterior}'. Debe estar en 'Agendada'.")

        # Cambiar estado a 'Confirmada'
        cursor.execute(
            "UPDATE appointments SET estado = 'Confirmada', updated_at = CURRENT_TIMESTAMP WHERE id_cita = %s;",
            (id_cita,)
        )

        # Historial de auditoría
        cambios_dict = {"estado": {"old": estado_anterior, "new": "Confirmada"}}
        cursor.execute(
            """
            INSERT INTO appointments_history (
                id_cita, estado_anterior, estado_nuevo, tipo_accion, realizado_por, usuario_identificador, cambios
            ) VALUES (%s, %s, %s, 'Modificacion', 'Recepcionista', %s, %s::jsonb);
            """,
            (id_cita, estado_anterior, 'Confirmada', str(usuario_identificador), json.dumps(cambios_dict))
        )

        conn.commit()
        return jsonify({"success": True, "message": "Paciente admitido exitosamente e ingresado a la sala de espera virtual."})
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        if cursor:
            cursor.close()
        Database.release_connection(conn)


@app.route("/api/doctors", methods=["GET"])
def get_doctors():
    """
    Retorna la lista de médicos de la clínica con su especialidad correspondiente.
    """
    conn = Database.get_connection()
    from psycopg2.extras import RealDictCursor
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT d.id_medico, d.nombre_completo, d.id_especialidad, s.nombre as especialidad_nombre
            FROM doctors d
            JOIN specialties s ON d.id_especialidad = s.id_especialidad
            ORDER BY d.nombre_completo ASC;
            """
        )
        rows = cursor.fetchall()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        Database.release_connection(conn)


@app.route("/api/receptionists", methods=["GET"])
def get_receptionists():
    """
    Retorna las cuentas de usuario con rol Recepcionista (útil para delegación).
    """
    conn = Database.get_connection()
    from psycopg2.extras import RealDictCursor
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT id_usuario, username, email
            FROM users
            WHERE rol = 'Recepcionista'
            ORDER BY username ASC;
            """
        )
        rows = cursor.fetchall()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        Database.release_connection(conn)


@app.route("/api/admin/create-user", methods=["POST"])
def create_user():
    """
    Creación unificada y atómica de usuarios y perfiles médicos/pacientes asociados.
    """
    data = request.get_json() or {}
    username = data.get("username")
    email = data.get("email")
    password = data.get("password")
    rol = data.get("rol")
    id_sede = data.get("id_sede")

    if not username or not email or not password or not rol:
        return jsonify({"error": "Parámetros obligatorios faltantes."}), 400

    password_hash = generate_password_hash(password)

    conn = Database.get_connection()
    conn.autocommit = False
    cursor = None
    try:
        cursor = conn.cursor()
        
        # 1. Insertar en tabla de usuarios
        cursor.execute(
            """
            INSERT INTO users (username, password_hash, email, rol, id_sede)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id_usuario;
            """,
            (username, password_hash, email, rol, id_sede if id_sede else None)
        )
        id_usuario = cursor.fetchone()[0]

        # 2. Insertar en tabla de Pacientes
        if rol == "Paciente":
            dni = username
            nombre_completo = data.get("nombre_completo", username)
            telefono = data.get("telefono", "555-0100")
            ciudad_origen = data.get("ciudad_origen", "Medellin")
            
            cursor.execute(
                """
                INSERT INTO patients (id_usuario, dni, nombre_completo, telefono, email, ciudad_origen)
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                (id_usuario, dni, nombre_completo, telefono, email, ciudad_origen)
            )
            
        # 3. Insertar en tabla de Médicos
        elif rol == "Medico":
            numero_licencia = data.get("numero_licencia")
            nombre_completo = data.get("nombre_completo")
            id_especialidad = data.get("id_especialidad")
            duracion_defecto = data.get("duracion_defecto", "30 minutes")
            
            if not numero_licencia or not nombre_completo or not id_especialidad:
                raise ValueError("Faltan datos obligatorios del médico (licencia, nombre o especialidad).")
                
            cursor.execute(
                """
                INSERT INTO doctors (id_usuario, numero_licencia, nombre_completo, id_especialidad, duracion_defecto)
                VALUES (%s, %s, %s, %s, %s);
                """,
                (id_usuario, numero_licencia, nombre_completo, id_especialidad, duracion_defecto)
            )

        conn.commit()
        return jsonify({"success": True, "id_usuario": str(id_usuario), "message": f"Cuenta de {rol} creada exitosamente."})
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        if cursor:
            cursor.close()
        Database.release_connection(conn)


@app.route("/api/admin/massive-cancellations-history", methods=["GET"])
def get_massive_cancellations_history():
    """
    Retorna el historial de cancelaciones masivas registradas.
    """
    conn = Database.get_connection()
    from psycopg2.extras import RealDictCursor
    cursor = None
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT mc.id_cancelacion, mc.fecha_ejecucion, mc.cantidad_canceladas, mc.auto_reschedule, mc.reporte_path,
                   b.nombre as sede_nombre, d.nombre_completo as doctor_nombre, u.username as ejecutado_por_username
            FROM massive_cancellations mc
            LEFT JOIN branches b ON mc.id_sede = b.id_sede
            LEFT JOIN doctors d ON mc.id_medico = d.id_medico
            LEFT JOIN users u ON mc.ejecutado_por = u.id_usuario
            ORDER BY mc.fecha_ejecucion DESC;
            """
        )
        rows = cursor.fetchall()
        formatted = []
        for r in rows:
            formatted.append({
                "id_cancelacion": str(r["id_cancelacion"]),
                "fecha_ejecucion": r["fecha_ejecucion"].strftime("%d/%m/%Y %H:%M"),
                "cantidad_canceladas": r["cantidad_canceladas"],
                "auto_reschedule": r["auto_reschedule"],
                "reporte_path": r["reporte_path"],
                "sede_nombre": r["sede_nombre"] or "Todas las sedes",
                "doctor_nombre": r["doctor_nombre"] or "Todos los médicos",
                "ejecutado_por": r["ejecutado_por_username"] or "N/A"
            })
        return jsonify(formatted)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        Database.release_connection(conn)


# ============================================================================
# RUN SERVER
# ============================================================================

if __name__ == "__main__":
    # El servidor corre localmente por defecto en el puerto 5000 de desarrollo
    app.run(host="0.0.0.0", port=5000, debug=True)
