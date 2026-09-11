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
import requests
import traceback
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
        """Busca un Task Type por su nombre (y opcionalmente entidad/departamento)."""
        return gazu.task.get_task_type_by_name(task_type_name, for_entity=for_entity, department=department)

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
        """Busca la tarea de una entidad para un Task Type y nombre dados."""
        return gazu.task.get_task_by_entity(entity, task_type, name=name)

    def update_task(self, task: dict) -> dict:
        """Persiste los cambios (incluida la metadata) de una tarea."""
        return gazu.task.update_task(task)

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
