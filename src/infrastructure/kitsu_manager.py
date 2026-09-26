# =========================================================================================
# OPENSTUDIOHUB
# Módulo: core/kitsu_manager.py
# Rol Arquitectónico: API Wrapper / Integración Gazu
# =========================================================================================
# Copyright (c) 2026 Ernesto Del Valle Macuare. Todos los derechos reservados.
# Licencia: GNU General Public License v3.0 (GPLv3)
#
# Autor: Ernesto Del Valle Macuare
# Versión del archivo: 1.7.0 (Gazu SSoT Wrappers)
# =========================================================================================

"""
Abstraction layer to communicate with Kitsu using the gazu library.
This module is the SINGLE SOURCE OF TRUTH (SSoT) for every gazu call in the
application: no other module should import or invoke gazu directly.

It wraps authentication (delegated by AuthManager), project management,
task/shot/asset/edit queries, file mapping and metadata updates.
"""

import gazu
import json
import requests
import traceback
from gazu.exception import NotAllowedException
from pathlib import Path
from typing import Optional, Tuple

from src.infrastructure.dev_defaults import (
    DEV_KITSU_ADMIN_EMAIL,
    DEV_KITSU_ADMIN_PASSWORD,
    DEV_KITSU_DUMMY_PASSWORD,
)

# Re-export para que los consumidores (p. ej. AuthManager) puedan capturar el
# error de autenticación de Gazu sin importar la librería directamente.
AuthFailedException = gazu.exception.AuthFailedException

class KitsuManager:
    def __init__(self):
        """
        El AuthManager asume la responsabilidad de establecer el host
        y los tokens globales de Gazu en RAM antes de instanciar esto.
        """
        pass

    def check_project_exists(self, project_name: str) -> bool:
        """
        Consulta a Kitsu si ya existe un proyecto con ese nombre exacto.
        Útil para prevenir conflictos antes de inicializar la topografía física.
        """
        try:
            proyecto = gazu.project.get_project_by_name(project_name)
            return proyecto is not None
        except Exception:
            # Gazu lanza una excepción si no encuentra el proyecto, o si hay un fallo de red.
            # Asumimos False (no existe) para permitir que el flujo superior decida.
            return False

    def check_health(self, timeout: float = 5.0) -> Tuple[bool, str]:
        """
        Pre-flight reachability probe against the Kitsu server.

        It only answers "is the server up?"; authentication and authorization are
        handled by the actual API calls. The probe hits the Kitsu root (the same
        target used by the Docker healthcheck) with no credentials, so any HTTP
        response means the server is alive. The short timeout protects against a
        black-holed network without producing the false negatives that a heavy
        authenticated endpoint did.
        """
        try:
            host = gazu.client.get_host()
        except Exception as error:  # noqa: BLE001
            return False, f"Kitsu host is not configured: {error}"

        if not host:
            return False, "Kitsu host is not configured."

        root = host.rstrip("/")
        if root.endswith("/api"):
            root = root[:-4]

        try:
            response = requests.get(root, timeout=timeout)
        except Exception as error:  # noqa: BLE001
            return False, f"Kitsu server unreachable: {error}"

        return True, f"Kitsu server is online (HTTP {response.status_code})."

    def get_project_by_name(self, project_name: str) -> Optional[dict]:
        """Returns the Kitsu project dict for an exact name, or ``None``."""
        try:
            return gazu.project.get_project_by_name(project_name)
        except Exception:  # noqa: BLE001 - missing project or network error
            return None

    def create_project(self, project_name: str) -> Tuple[bool, str, dict]:
        """
        Construye la entidad raíz del Proyecto en la base de datos de Kitsu.
        Valida pre-existencias y captura el ID resultante para enlazado (Binding).
        """
        try:
            # 1. Validación de colisión
            if self.check_project_exists(project_name):
                return False, f"El proyecto '{project_name}' ya existe en la base de datos de Kitsu.", {}

            # 2. Generación en Base de Datos
            nuevo_proyecto = gazu.project.new_project(project_name)

            if not nuevo_proyecto:
                return False, "Kitsu rechazó la creación del proyecto (respuesta vacía).", {}

            return True, "Proyecto creado exitosamente en Kitsu.", nuevo_proyecto

        except Exception as e:
            return False, f"Error crítico al comunicarse con Kitsu: {str(e)}", {}

    def create_initial_edit(self, project_id: str, edit_name: str = "Main Edit") -> Tuple[bool, str, dict]:
        """
        Crea un Edit (entidad de montaje) inicial en el proyecto.
        Fundamental para que el departamento de Editorial tenga un contenedor en la base de datos.
        """
        if not project_id:
            return False, "ID de proyecto inválido.", {}

        try:
            # 1. Verificar si ya existe para evitar duplicados
            existing_edit = gazu.edit.get_edit_by_name(project_id, edit_name)
            if existing_edit:
                return True, f"El Edit '{edit_name}' ya existe en Kitsu.", existing_edit

            # 2. Crear la nueva entidad Edit
            nuevo_edit = gazu.edit.new_edit(project_id, name=edit_name)
            return True, f"Edit '{edit_name}' creado exitosamente.", nuevo_edit

        except Exception as e:
            trace = traceback.format_exc()
            print(f"[KitsuManager] DEBUG CRÍTICO (create_initial_edit):\n{trace}")
            return False, f"Fallo al crear el Edit inicial: {str(e)}", {}

    def upload_project_splash(self, project_id: str, image_path: str) -> bool:
        """
        Inyecta el Splash Screen (Thumbnail) oficial del proyecto.
        Captura silenciosamente los errores porque esto no debe bloquear la creación.
        """
        if not image_path:
            return False

        img_path = Path(image_path)
        if not img_path.exists() or not img_path.is_file():
            return False

        try:
            project = gazu.project.get_project(project_id)
            if project:
                endpoint = f"/pictures/thumbnails/projects/{project_id}"
                gazu.client.upload(endpoint, str(img_path))
                return True
        except Exception as e:
            print(f"[KitsuManager] Advertencia: Fallo al subir el Splash Screen a Kitsu: {e}")

        return False

    def delete_project(self, project_id: str) -> Tuple[bool, str]:
        """
        Ejecuta la eliminación permanente del proyecto en la base de datos.
        Utiliza el método nativo remove_project con force=True para saltar
        la restricción de estado 'Closed', garantizando una limpieza limpia.
        """
        if not project_id:
            return False, "ID de proyecto inválido o nulo."

        try:
            # Reemplazo de Two-Step Destruction por Force Remove nativo de Gazu.

            try:
                gazu.project.close_project(project_id)
                print(f"[KitsuManager] Proyecto '{project_id}' cambiado a estado 'Closed'.")
            except Exception as close_err:
                print(f"[KitsuManager] Advertencia al intentar cerrar el proyecto: {close_err}")

            gazu.project.remove_project(project_id, force=True)
            return True, "Proyecto destruido exitosamente en Kitsu."

        except Exception as e:
            error_msg = str(e)
            print(f"[KitsuManager] Error crítico al borrar el proyecto '{project_id}': {error_msg}")
            return False, f"Fallo al eliminar en Kitsu: {error_msg}"

    def build_web_url(self, host_url: str, project_id: str, sub_path: str) -> str:
        """
        Construye una URL segura para enrutar al usuario a la interfaz web de Kitsu.
        Sanea automáticamente la URL base removiendo '/api' si está presente.
        Ejemplo sub_path: '/shots', '/team', '/production-settings'
        """
        if not host_url or not project_id:
            return ""

        clean_host = host_url[:-4] if host_url.endswith('/api') else host_url

        if sub_path and not sub_path.startswith('/'):
            sub_path = '/' + sub_path

        return f"{clean_host}/productions/{project_id}{sub_path}"

    def download_project_thumbnail(self, project_id: str, token: str, host_url: str) -> Optional[bytes]:
        """
        Descarga asíncronamente la miniatura del proyecto usando la API HTTP cruda.
        Retorna los bytes de la imagen listos para el QImage o None si falla.
        """
        if not project_id or not token or not host_url:
            return None

        try:
            img_url = f"{host_url}/pictures/thumbnails/projects/{project_id}.png"
            headers = {"Authorization": f"Bearer {token}"}

            response = requests.get(img_url, headers=headers, timeout=10)

            if response.status_code == 200:
                return response.content
        except Exception as e:
            print(f"[KitsuManager] Fallo de red al descargar miniatura del proyecto '{project_id}': {e}")

        return None

    def seed_test_database(self, admin_email: str = DEV_KITSU_ADMIN_EMAIL, admin_pwd: str = DEV_KITSU_ADMIN_PASSWORD) -> Tuple[bool, str]:
        """
        Se conecta temporalmente como administrador global para inyectar
        los usuarios dummy necesarios para las pruebas locales del Hub.
        """
        try:
            # 1. Autenticación efímera de administración
            gazu.log_in(admin_email, admin_pwd)
            print("[KitsuManager] Autenticado como Admin. Iniciando sembrado de cuentas de prueba...")

            # 2. Definición de la matriz de usuarios dummy requerida
            dummy_users = [
                {"first": "Production", "last": "Manager", "email": "pm@estudiomacuare.com", "role": "manager"},
                {"first": "Vendor", "last": "Artist", "email": "vendor@estudiomacuare.com", "role": "vendor"},
                {"first": "3D", "last": "Artist", "email": "artist@estudiomacuare.com", "role": "user"}
            ]

            creados = 0
            for user in dummy_users:
                # Verificar si el usuario ya fue inyectado previamente para evitar duplicados
                existing = gazu.person.get_person_by_email(user["email"])
                if not existing:
                    gazu.person.new_person(
                        first_name=user["first"],
                        last_name=user["last"],
                        email=user["email"],
                        role=user["role"],
                        password=DEV_KITSU_DUMMY_PASSWORD
                    )
                    print(f"[KitsuManager] -> Usuario creado: {user['email']}")
                    creados += 1
                else:
                    print(f"[KitsuManager] -> Usuario ya existía: {user['email']}")

            return True, f"Base de datos sembrada. {creados} nuevos usuarios creados con éxito."

        except Exception as e:
            return False, f"Fallo crítico durante el Seeding de Kitsu: {str(e)}"

    def get_all_templates(self) -> list:
        """
        Consulta la base de datos de Kitsu y devuelve una lista con
        todos los esquemas de producción (Project Templates) disponibles.
        """
        try:
            return gazu.project_template.all_project_templates()
        except Exception as e:
            print(f"[KitsuManager] Error al consultar plantillas: {e}")
            return []

    def create_project_from_template(self, project_name: str, template_name: str) -> Tuple[bool, str, dict]:
        """
        Construye el proyecto inyectando la estructura de una plantilla de Kitsu.
        """
        try:
            if self.check_project_exists(project_name):
                return False, f"El proyecto '{project_name}' ya existe.", {}

            # 1. Buscar la plantilla por su nombre real
            template = gazu.project_template.get_project_template_by_name(template_name)

            # 2. Forjar el proyecto
            if template:
                print(f"[KitsuManager] Utilizando plantilla de Kitsu: {template_name}")
                nuevo_proyecto = gazu.project.new_project(name=project_name, project_template=template)
            else:
                print(f"[KitsuManager] WARNING: Plantilla '{template_name}' no encontrada. Creando proyecto en blanco.")
                nuevo_proyecto = gazu.project.new_project(project_name)

            if not nuevo_proyecto:
                return False, "Kitsu rechazó la creación del proyecto.", {}

            return True, "Project created successfully.", nuevo_proyecto

        except Exception as e:
            return False, f"Error crítico: {str(e)}", {}

    def check_edit_preview_exists(self, project_id: str) -> bool:
        """
        Verifica si existe al menos un archivo de previsualización (preview-file)
        para la tarea de Edición en Kitsu. Retorna True si hay video, False si no.
        """
        try:
            edits = gazu.client.get(f"data/edits/with-tasks?project_id={project_id}")
            if not edits:
                return False

            for e in edits:
                if e.get('canceled'):
                    continue

                # Buscar el Task Type de 'Edit'
                r_task_types = gazu.client.get(f"data/edits/{e['id']}/task-types")
                edit_task_id = None
                for tt in r_task_types:
                    if tt['name'] == 'Edit':
                        edit_task_id = tt['id']
                        break

                if not edit_task_id:
                    continue

                # Buscar previews
                r_previews = gazu.client.get(f"data/edits/{e['id']}/preview-files")
                if not r_previews:
                    continue

                preview_list = r_previews.get(edit_task_id, [])
                if preview_list and len(preview_list) > 0 and preview_list[0] is not None:
                    return True

            return False

        except Exception as e:
            print(f"[KitsuManager] Error verificando la existencia de previews de edición: {e}")
            return False

    def get_all_projects(self) -> dict :
        return gazu.project.all_open_projects()

    # =========================================================================
    # GAZU API WRAPPERS (SSoT)
    # Todas las llamadas a Gazu de la aplicación DEBEN pasar por estos métodos.
    # Las firmas replican las de la librería gazu para preservar el
    # comportamiento exacto de los consumidores.
    # =========================================================================

    # ------------------------------------------------------------------
    # Sesión y autenticación (consumido por AuthManager)
    # ------------------------------------------------------------------

    def set_host(self, host_url: str) -> None:
        """Establece el host global de Gazu en RAM."""
        gazu.client.set_host(host_url)

    def log_in(self, email: str, password: str) -> dict:
        """
        Autentica contra Kitsu y almacena los tokens en RAM.
        Lanza AuthFailedException si las credenciales son inválidas.
        """
        return gazu.log_in(email, password)

    def set_tokens(self, tokens: dict) -> dict:
        """Inyecta tokens de sesión previamente guardados en RAM."""
        return gazu.client.set_tokens(tokens)

    def get_current_user(self) -> dict:
        """Devuelve el usuario autenticado actualmente en Gazu."""
        return gazu.client.get_current_user()

    def log_out(self) -> dict:
        """Cierra la sesión actual de Gazu."""
        return gazu.log_out()

    def get_access_token(self) -> str:
        """Extrae el access token vigente desde el estado global de Gazu."""
        if hasattr(gazu.client, "tokens") and isinstance(gazu.client.tokens, dict):
            return gazu.client.tokens.get("access_token", "")
        return ""

    def has_session_tokens(self) -> bool:
        """True si Gazu tiene un diccionario de tokens cargado en RAM."""
        return hasattr(gazu.client, "tokens") and isinstance(gazu.client.tokens, dict)

    def get_organisation(self) -> dict:
        """Devuelve la organización (estudio) configurada en Kitsu."""
        return gazu.person.get_organisation()

    # ------------------------------------------------------------------
    # Proyectos
    # ------------------------------------------------------------------

    def get_project(self, project_id: str) -> dict:
        """Devuelve un proyecto por su ID."""
        return gazu.project.get_project(project_id)

    def all_projects(self) -> list:
        """Devuelve TODOS los proyectos registrados (incluyendo cerrados)."""
        return gazu.project.all_projects()

    # ------------------------------------------------------------------
    # Tareas
    # ------------------------------------------------------------------

    def get_task(self, task_id: str) -> dict:
        """Devuelve una tarea por su ID."""
        return gazu.task.get_task(task_id)

    def all_tasks_to_do(self) -> list:
        """Devuelve todas las tareas pendientes del usuario autenticado."""
        return gazu.user.all_tasks_to_do()

    def all_tasks_for_person(self, person) -> list:
        """Devuelve las tareas abiertas asignadas a una persona."""
        return gazu.task.all_tasks_for_person(person)

    def all_done_tasks_for_person(self, person) -> list:
        """Devuelve las tareas finalizadas asignadas a una persona."""
        return gazu.task.all_done_tasks_for_person(person)

    def all_tasks_for_project(self, project_id) -> list:
        """Devuelve todas las tareas de un proyecto."""
        return gazu.task.all_tasks_for_project(project_id)

    def all_tasks_for_edit(self, edit) -> list:
        """Devuelve las tareas vinculadas a un Edit."""
        return gazu.task.all_tasks_for_edit(edit)

    def all_task_types(self) -> list:
        """Devuelve todos los Task Types globales."""
        return gazu.task.all_task_types()

    def get_task_type_by_name(self, task_type_name: str, for_entity: str = None, department=None) -> dict:
        """Busca un Task Type por su nombre (y opcionalmente entidad/departamento).

        The ``for_entity``/``department`` kwargs only exist in newer gazu. The
        Blender add-on sandbox bundles an older gazu (0.9.x), so fall back to a
        plain name lookup when the running gazu rejects them.
        """
        try:
            return gazu.task.get_task_type_by_name(
                task_type_name, for_entity=for_entity, department=department
            )
        except TypeError:
            return gazu.task.get_task_type_by_name(task_type_name)

    def create_task(self, entity, task_type, name: str = None, task_status=None) -> dict:
        """Crea una tarea para una entidad y un Task Type dados."""
        return gazu.task.create_task(entity, task_type, name=name, task_status=task_status)

    def new_task(self, entity, task_type, name: str = "main", task_status=None,
                 assigner=None, assignees=None) -> dict:
        """Crea una tarea nueva (o devuelve la existente) para la entidad."""
        return gazu.task.new_task(
            entity, task_type,
            name=name, task_status=task_status,
            assigner=assigner, assignees=assignees
        )

    def get_task_by_entity(self, entity, task_type, name: str = "main") -> dict:
        """Busca la tarea de una entidad para un Task Type y nombre dados.

        Newer gazu accepts a ``name`` kwarg on ``get_task_by_entity``; older gazu
        (bundled with the Blender add-on) only exposes it on ``get_task_by_name``.
        """
        try:
            return gazu.task.get_task_by_entity(entity, task_type, name=name)
        except TypeError:
            return gazu.task.get_task_by_name(entity, task_type, name=name)

    def update_task(self, task: dict) -> dict:
        """Persiste los cambios (incluida la metadata) de una tarea."""
        return gazu.task.update_task(task)

    def get_host(self) -> str:
        """Return the currently active Kitsu API host."""
        try:
            return gazu.client.get_host()
        except Exception:  # noqa: BLE001
            return ""

    def _raw_put(self, path: str, payload: dict):
        """Low-level PUT used only to capture the server response on failure."""
        client = gazu.client.default_client
        url = gazu.client.get_full_url(path, client=client)
        headers = gazu.client.make_auth_header(client=client)
        headers["Content-Type"] = "application/json"
        return client.session.put(
            url,
            data=json.dumps(payload, cls=gazu.client.CustomJSONEncoder),
            headers=headers,
        )

    def update_task_data(self, task: dict, data: dict) -> dict:
        """Persiste el custom data (metadata) de una tarea.

        Only ``id`` and ``data`` are sent: Zou merges ``data`` into the task's
        JSONB metadata, and a minimal payload avoids shipping read-only or
        expanded fields back to the server.
        """
        task_id = task.get("id") if isinstance(task, dict) else str(task or "")
        payload = {"id": task_id, "data": dict(data)}
        try:
            return gazu.task.update_task(payload)
        except NotAllowedException as error:
            self._log_task_update_failure(task_id, payload, error)
            raise PermissionError(
                "Kitsu denied the task update (403). The signed-in account needs "
                "the 'manager' role on this project (or be a global admin)."
            ) from error
        except Exception as error:  # noqa: BLE001
            self._log_task_update_failure(task_id, payload, error)
            raise

    def _log_task_update_failure(self, task_id: str, payload: dict, error: Exception) -> None:
        try:
            response = self._raw_put(f"data/tasks/{task_id}", payload)
            print(
                f"[KitsuManager] Task '{task_id}' update failed on "
                f"'{self.get_host()}' ({error}) | HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )
        except Exception as diagnostic_error:  # noqa: BLE001
            print(f"[KitsuManager] Task '{task_id}' update diagnostics failed: {diagnostic_error}")

    def all_tasks_for_asset(self, asset) -> list:
        """Devuelve todas las tareas de un Asset."""
        return gazu.task.all_tasks_for_asset(asset)

    def get_default_task_status(self) -> dict:
        """Devuelve el Task Status por defecto del estudio."""
        return gazu.task.get_default_task_status()

    def new_task_type(self, name: str, color: str = "#000000", for_entity: str = "Asset") -> dict:
        """Crea (o devuelve) un Task Type global con el nombre dado."""
        return gazu.task.new_task_type(name, color=color, for_entity=for_entity)

    # ------------------------------------------------------------------
    # Shots y Secuencias
    # ------------------------------------------------------------------

    def all_shots_for_project(self, project_id) -> list:
        """Devuelve todos los Shots de un proyecto."""
        return gazu.shot.all_shots_for_project(project_id)

    def get_sequence(self, sequence_id: str) -> dict:
        """Devuelve una secuencia por su ID."""
        return gazu.shot.get_sequence(sequence_id)

    def all_sequences_for_project(self, project_id) -> list:
        """Devuelve todas las secuencias de un proyecto."""
        return gazu.shot.all_sequences_for_project(project_id)

    def get_sequence_by_name(self, project_id, sequence_name: str, episode=None) -> dict:
        """Busca una secuencia por nombre dentro de un proyecto."""
        return gazu.shot.get_sequence_by_name(project_id, sequence_name, episode=episode)

    def new_sequence(self, project, name: str, episode=None) -> dict:
        """Crea una secuencia en el proyecto (o devuelve la existente)."""
        return gazu.shot.new_sequence(project, name=name, episode=episode)

    def update_sequence_data(self, sequence, data: dict = None) -> dict:
        """Actualiza la metadata (custom data) de una secuencia."""
        return gazu.shot.update_sequence_data(sequence, data=data)

    # ------------------------------------------------------------------
    # Assets
    # ------------------------------------------------------------------

    def all_assets_for_project(self, project_id) -> list:
        """Devuelve todos los Assets de un proyecto."""
        return gazu.asset.all_assets_for_project(project_id)

    def get_asset_type(self, asset_type_id: str) -> dict:
        """Devuelve un Asset Type por su ID."""
        return gazu.asset.get_asset_type(asset_type_id)

    def all_asset_types(self) -> list:
        """Devuelve todos los Asset Types globales."""
        return gazu.asset.all_asset_types()

    def get_asset(self, asset_id: str) -> dict:
        """Devuelve un Asset por su ID."""
        return gazu.asset.get_asset(asset_id)

    def update_asset(self, asset: dict) -> dict:
        """Persiste los cambios de un Asset en Kitsu."""
        return gazu.asset.update_asset(asset)

    # ------------------------------------------------------------------
    # Entidades (metadata / custom data)
    # ------------------------------------------------------------------

    def update_entity_data(self, entity_id: str, data: dict) -> dict:
        """Inyecta metadata (custom data) en una entidad genérica."""
        return gazu.entity.update_entity_data(entity_id, data)

    # ------------------------------------------------------------------
    # Edits
    # ------------------------------------------------------------------

    def all_edits_for_project(self, project_id) -> list:
        """Devuelve todos los Edits de un proyecto."""
        return gazu.edit.all_edits_for_project(project_id)

    # ------------------------------------------------------------------
    # Files / Software
    # ------------------------------------------------------------------

    def get_software_by_name(self, software_name: str) -> dict:
        """Busca un software registrado en Kitsu por su nombre."""
        return gazu.files.get_software_by_name(software_name)

    def new_working_file(self, task, name: str = "main", mode: str = "working",
                         software=None, comment: str = "", person=None,
                         revision: int = 0, sep: str = "/") -> dict:
        """Registra un working file para una tarea."""
        return gazu.files.new_working_file(
            task, name=name, mode=mode, software=software,
            comment=comment, person=person, revision=revision, sep=sep
        )

    # =========================================================================
    # PHASE 2 — .oshproject export/import wrappers (still the gazu SSoT)
    # Read, download and write operations used by the Kitsu migration services.
    # =========================================================================

    # ------------------------------------------------------------------
    # Project metadata
    # ------------------------------------------------------------------
    def update_project_data(self, project, data: dict) -> dict:
        """Persist the custom data (metadata) of a project."""
        return gazu.project.update_project_data(project, data=data)

    def update_project(self, project: dict) -> dict:
        """Persist mutable project fields (name, status, fps, ...)."""
        return gazu.project.update_project(project)

    def new_software(self, name: str, short_name: str = "") -> dict:
        """Create a software entry used by working files."""
        return gazu.files.new_software(name, short_name=short_name or name)

    def all_project_status(self) -> list:
        """All project statuses defined on the server."""
        return gazu.project.all_project_status()

    def get_project_status_by_name(self, name: str):
        """Project status by name, or ``None``."""
        return gazu.project.get_project_status_by_name(name)

    # ------------------------------------------------------------------
    # People & studio resources
    # ------------------------------------------------------------------
    def all_persons(self) -> list:
        """Every person registered on the server."""
        return gazu.person.all_persons()

    def get_person_by_email(self, email: str):
        """Person by email, or ``None``."""
        try:
            return gazu.person.get_person_by_email(email)
        except Exception:  # noqa: BLE001 - not found / network
            return None

    def new_person(self, first_name: str, last_name: str, email: str,
                   role: str = "user", password=None, departments=None,
                   active: bool = True) -> dict:
        """Create a person. ``password=None`` creates the account with no password."""
        return gazu.person.new_person(
            first_name=first_name, last_name=last_name, email=email,
            role=role, password=password, departments=departments, active=active,
        )

    def add_person_to_team(self, project, person, role=None) -> dict:
        """Add a person to a project team (optionally with a role)."""
        return gazu.project.add_person_to_team(project, person, role=role)

    def update_team_member_role(self, project, person, role: Optional[str]) -> dict:
        """Set (or clear with ``None``) a person's project-specific role."""
        return gazu.project.update_team_member_role(project, person, role=role)

    def all_departments(self) -> list:
        """All departments defined on the server."""
        return gazu.person.all_departments()

    def get_department_by_name(self, name: str):
        """Department by name, or ``None``."""
        return gazu.person.get_department_by_name(name)

    def new_department(self, name: str, color: str = "") -> dict:
        """Create a department."""
        return gazu.person.new_department(name, color=color)

    def all_task_statuses(self) -> list:
        """All global task statuses."""
        return gazu.task.all_task_statuses()

    def all_task_statuses_for_project(self, project) -> list:
        """Task statuses available on a project."""
        return gazu.task.all_task_statuses_for_project(project)

    def get_task_status_by_name(self, name: str):
        """Task status by name, or ``None``."""
        return gazu.task.get_task_status_by_name(name)

    def get_task_status(self, task_status_id: str) -> dict:
        """Task status by id."""
        return gazu.task.get_task_status(task_status_id)

    def new_task_status(self, name: str, short_name: str = "", color: str = "#000000") -> dict:
        """Create a global task status (short name/colour help the UI)."""
        return gazu.task.new_task_status(name, short_name=short_name or name[:4], color=color)

    def link_task_status_to_project(self, project_id: str, task_status_id: str) -> dict:
        """Link an existing global task status to a production.

        Imported/migrated productions can end up with tasks pointing at global
        statuses while the production itself has no ``project_task_status_link``
        entries. Kitsu (and therefore to the per-project status APIs) then
        reports an empty status list. This wraps the manager-only endpoint.
        """
        project_id = project_id.get("id", "") if isinstance(project_id, dict) else project_id
        task_status_id = (
            task_status_id.get("id", "") if isinstance(task_status_id, dict) else task_status_id
        )
        return gazu.client.post(
            f"data/projects/{project_id}/settings/task-status",
            {"task_status_id": task_status_id},
        )

    def new_asset_type(self, name: str) -> dict:
        """Create a global asset type."""
        return gazu.asset.new_asset_type(name)

    def get_asset_type_by_name(self, name: str):
        """Asset type by name, or ``None``."""
        return gazu.asset.get_asset_type_by_name(name)

    # ------------------------------------------------------------------
    # Entities
    # ------------------------------------------------------------------
    def all_episodes_for_project(self, project) -> list:
        """All episodes of a project."""
        return gazu.shot.all_episodes_for_project(project)

    def get_episode_by_name(self, project, name: str):
        """Episode by name within a project, or ``None``."""
        return gazu.shot.get_episode_by_name(project, name)

    def new_episode(self, project, name: str) -> dict:
        """Create an episode."""
        return gazu.shot.new_episode(project, name=name)

    def new_shot(self, project, sequence, name: str, nb_frames=None, frame_in=None,
                 frame_out=None, description=None, data=None) -> dict:
        """Create a shot."""
        return gazu.shot.new_shot(
            project, sequence, name=name, nb_frames=nb_frames, frame_in=frame_in,
            frame_out=frame_out, description=description, data=data,
        )

    def get_shot_by_name(self, sequence, name: str):
        """Shot by name within a sequence, or ``None``."""
        return gazu.shot.get_shot_by_name(sequence, name)

    def new_asset(self, project, asset_type, name: str, description=None,
                  extra_data=None, episode=None, is_shared: bool = False) -> dict:
        """Create an asset."""
        return gazu.asset.new_asset(
            project, asset_type, name=name, description=description,
            extra_data=extra_data, episode=episode, is_shared=is_shared,
        )

    def get_asset_by_name(self, project, name: str, asset_type=None):
        """Asset by name within a project, or ``None``."""
        return gazu.asset.get_asset_by_name(project, name, asset_type=asset_type)

    def new_edit(self, project, name: str, description=None, data=None, episode=None) -> dict:
        """Create an edit."""
        return gazu.edit.new_edit(
            project, name=name, description=description, data=data, episode=episode,
        )

    def get_edit_by_name(self, project, name: str):
        """Edit by name within a project, or ``None``."""
        return gazu.edit.get_edit_by_name(project, name)

    def update_shot_data(self, shot, data: dict) -> dict:
        """Persist the custom data of a shot."""
        return gazu.shot.update_shot_data(shot, data=data)

    def update_asset_data(self, asset, data: dict) -> dict:
        """Persist the custom data of an asset."""
        return gazu.asset.update_asset_data(asset, data=data)

    def update_edit_data(self, edit, data: dict) -> dict:
        """Persist the custom data of an edit."""
        return gazu.edit.update_edit_data(edit, data=data)

    # ------------------------------------------------------------------
    # Casting
    # ------------------------------------------------------------------
    def get_project_shots_casting(self, project) -> dict:
        """Shot casting map for a project, keyed by shot id."""
        return gazu.casting.get_project_shots_casting(project)

    def all_entity_links_for_project(self, project) -> list:
        """Every entity link (asset instances, etc.) of a project."""
        return gazu.casting.all_entity_links_for_project(project)

    def cast_asset(self, project, entities, asset, nb_occurences=None, label=None) -> dict:
        """Cast an asset into one or many entities."""
        return gazu.casting.cast_asset(
            project, entities, asset, nb_occurences=nb_occurences, label=label,
        )

    def update_shot_casting(self, project, shot, casting: dict) -> dict:
        """Replace the casting of a shot."""
        return gazu.casting.update_shot_casting(project, shot, casting)

    def update_asset_casting(self, project, asset, casting: dict) -> dict:
        """Replace the casting of an asset."""
        return gazu.casting.update_asset_casting(project, asset, casting)

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------
    def create_entity_tasks(self, entity, task_types: list) -> list:
        """Create the standard set of tasks for an entity in one call."""
        return gazu.task.create_entity_tasks(entity, task_types)

    def update_task_status(self, task) -> dict:
        """Persist a task's status (the dict carries the status id)."""
        return gazu.task.update_task_status(task)

    def assign_task(self, task, person) -> dict:
        """Assign a task to a person."""
        return gazu.task.assign_task(task, person)

    # ------------------------------------------------------------------
    # Comments, previews and attachments
    # ------------------------------------------------------------------
    def all_comments_for_project(self, project) -> list:
        """Every comment of a project."""
        return gazu.task.all_comments_for_project(project)

    def all_comments_for_task(self, task) -> list:
        """Every comment of a task."""
        return gazu.task.all_comments_for_task(task)

    def add_comment(self, task, task_status, comment: str = "", person=None,
                    attachments=None, created_at=None, checklist=None,
                    for_client: bool = False) -> dict:
        """Add a comment (optionally with attachments/checklist) to a task."""
        return gazu.task.add_comment(
            task, task_status, comment=comment, person=person,
            attachments=attachments, created_at=created_at, checklist=checklist,
            for_client=for_client,
        )

    def reply_to_comment(self, task, comment, text: str, person=None) -> dict:
        """Reply to an existing comment."""
        return gazu.task.reply_to_comment(task, comment, text, person=person)

    def add_attachment_files_to_comment(self, task, comment, attachments) -> dict:
        """Upload attachment file(s) onto an existing comment."""
        return gazu.task.add_attachment_files_to_comment(task, comment, attachments)

    def all_previews_for_task(self, task) -> list:
        """Every preview of a task."""
        return gazu.task.all_previews_for_task(task)

    def all_preview_files_for_project(self, project) -> list:
        """Every preview file of a project."""
        return gazu.task.all_preview_files_for_project(project)

    def publish_preview(self, task, task_status, comment: str = "", person=None,
                        preview_file_path=None, preview_file_url=None,
                        attachments=None, revision=None, set_thumbnail: bool = False):
        """Publish a preview (with an uploaded movie path/url) and return ``(comment, preview)``."""
        return gazu.task.publish_preview(
            task, task_status, comment=comment, person=person,
            preview_file_path=preview_file_path, preview_file_url=preview_file_url,
            attachments=attachments, revision=revision, set_thumbnail=set_thumbnail,
        )

    def create_preview(self, task, comment, revision=None) -> dict:
        """Create an empty preview slot on a comment."""
        return gazu.task.create_preview(task, comment, revision=revision)

    # ------------------------------------------------------------------
    # Working files, attachments and time sheets
    # ------------------------------------------------------------------
    def get_working_files_for_task(self, task) -> list:
        """Working-file revision metadata for a task."""
        return gazu.files.get_working_files_for_task(task)

    def get_all_working_files_for_entity(self, entity, task=None, name=None) -> list:
        """Working-file revision metadata for an entity."""
        return gazu.files.get_all_working_files_for_entity(entity, task=task, name=name)

    def get_all_attachment_files_for_project(self, project) -> list:
        """Attachment file metadata for a project."""
        return gazu.files.get_all_attachment_files_for_project(project)

    def get_all_attachment_files_for_task(self, task) -> list:
        """Attachment file metadata for a task."""
        return gazu.files.get_all_attachment_files_for_task(task)

    def get_time_spent(self, task, date=None) -> dict:
        """Time-spent sheet of a task (optionally for one date)."""
        return gazu.task.get_time_spent(task, date=date)

    def add_time_spent(self, task, person, date: str, duration: int) -> dict:
        """Add a time-spent entry for a person on a date."""
        return gazu.task.add_time_spent(task, person, date=date, duration=duration)

    def set_time_spent(self, task, person, date: str, duration: int) -> dict:
        """Set (replace) a time-spent entry for a person on a date."""
        return gazu.task.set_time_spent(task, person, date=date, duration=duration)

    # ------------------------------------------------------------------
    # Downloads (streamed to a destination path by gazu)
    # ------------------------------------------------------------------
    def download_preview_file(self, preview_file, file_path: str, progress_callback=None):
        """Download a still preview image to ``file_path``."""
        return gazu.files.download_preview_file(
            preview_file, file_path, progress_callback=progress_callback
        )

    def download_preview_movie(self, preview_file, file_path: str, progress_callback=None):
        """Download a preview movie to ``file_path``."""
        return gazu.files.download_preview_movie(
            preview_file, file_path, progress_callback=progress_callback
        )

    def download_preview_lowdef_movie(self, preview_file, file_path: str, progress_callback=None):
        """Download the low-definition preview movie to ``file_path``."""
        return gazu.files.download_preview_lowdef_movie(
            preview_file, file_path, progress_callback=progress_callback
        )

    def download_preview_file_thumbnail(self, preview_file, file_path: str, progress_callback=None):
        """Download a preview thumbnail to ``file_path``."""
        return gazu.files.download_preview_file_thumbnail(
            preview_file, file_path, progress_callback=progress_callback
        )

    def download_attachment_file(self, attachment_file, file_path: str, progress_callback=None):
        """Download a comment attachment to ``file_path``."""
        return gazu.files.download_attachment_file(
            attachment_file, file_path, progress_callback=progress_callback
        )
