"""
Standalone test-harness settings for exercising `rm_workflow` independently
(mirrors rm_auth_tenant's own config/settings.py). A consuming platform
project would NOT use this file -- it defines its own settings and adds
`rm_auth` (shared/platform app), `rm_auth_tenant` (tenant-scoped identity),
and `rm_workflow` (this app) to INSTALLED_APPS.

This harness installs `rm_auth` and `rm_auth_tenant` as normal dependencies
(their wheels, same as `drf_base`) purely to satisfy rm_workflow's own
cross-app references: the local Tenant mirror's sync source (rm_auth.Tenant,
via TenantMirrorRegistry -- see rm_workflow/tenants/models.py),
AUTH_USER_MODEL (rm_auth_tenant.User, for RMAuditModel's created_by/
updated_by), RequiresPermission (rm_auth_tenant.authorization.
policy_permission), and JWTAuthentication/TenantResolutionMiddleware/
SecurityContextMiddleware.

Like rm_auth_tenant's harness, this does NOT run django-tenants' real
schema-per-tenant machinery (migrate_schemas / actual schema switching) --
that's the composing platform project's job. This harness tests rm_workflow's
models/services/API against a single plain schema.
"""

import os
from pathlib import Path

import rm_auth_tenant
from drf_base_app.logging.config import setup as configure_logging
from drf_base_app.tenancy.settings import (
    get_default_persona_name,
    get_default_tenant_id,
)

BASE_DIR = Path(__file__).resolve().parent.parent

# rm_auth_tenant is consumed here as an installed wheel, not vendored
# source -- there's no "rm_auth_tenant/" directory under BASE_DIR the way
# there is in rm_auth_tenant's own test harness. Resolve the packaged
# casbin_model.conf relative to the installed package itself instead.
RM_AUTH_TENANT_DIR = Path(rm_auth_tenant.__file__).resolve().parent

configure_logging(level=os.environ.get("LOG_LEVEL"))

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-for-production")
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

# django_tenants requires SHARED_APPS/TENANT_APPS to exist even in a harness
# like this one that never actually runs migrate_schemas or switches
# schemas -- its own AppConfig.ready() checks for TENANT_APPS
# unconditionally (see rm_auth_tenant's own settings.py for the same note).
SHARED_APPS = [
    "django_tenants",  # provides TenantMixin/DomainMixin used by rm_auth.tenants.models
    "django.contrib.contenttypes",
    "django.contrib.auth",  # kept only for Django admin/permission plumbing compatibility
    "django.contrib.admin",  # /admin/ -- is_superuser-gated, platform-only NodeType catalog editing
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "rm_auth",  # shared/platform app -- Tenant, Domain, Action (dependency, not this repo's code)
    "django.contrib.messages",
    "drf_base_app",
]

TENANT_APPS = [
    "rm_auth_tenant",  # tenant-scoped identity -- dependency, not this repo's code
    "rm_workflow",  # this repo
]

INSTALLED_APPS = list(SHARED_APPS) + [
    app for app in TENANT_APPS if app not in SHARED_APPS
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Resolves tenant_id from subdomain/header/JWT claim onto request --
    # stays in rm_auth (shared). See the "Tier B Implementation Plan" doc,
    # section 0.1.
    "rm_auth.middleware.tenant_resolution.TenantResolutionMiddleware",
    "drf_base_app.logging.middleware.RequestContextMiddleware",
    "rm_auth.middleware.security_context.SecurityContextMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        # django_tenants' backend, NOT plain django.db.backends.postgresql --
        # required the moment any model uses TenantMixin/DomainMixin
        # (rm_auth's Tenant/Domain do), even though this harness never
        # itself calls migrate_schemas or switches schemas.
        "ENGINE": "django_tenants.postgresql_backend",
        # Deliberately a DIFFERENT default database name than rm_auth_project's
        # or rm_auth_tenant's own harnesses -- three separate Django projects
        # with independent migration histories; pointing more than one at the
        # same physical database produces InconsistentMigrationHistory
        # errors (see the "Tier B Implementation Plan" doc's correction note
        # for the incident that caused this originally).
        "NAME": os.environ.get("POSTGRES_DB", "rm_auth_tenant_appdb"),
        "USER": os.environ.get("POSTGRES_USER", "appuser"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "apppassword"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "0")),
    }
}
HAS_MULTI_TYPE_TENANTS = False
DATABASE_ROUTERS = ["drf_base_app.tenancy.routers.HybridTenantSyncRouter"]
TENANT_SYNC_ROUTER = "drf_base_app.tenancy.routers.HybridTenantSyncRouter"

# Required as soon as rm_auth.tenants.models (Tenant/Domain) is imported --
# django_tenants builds a real ForeignKey field from these settings at
# class-definition time.
TENANT_MODEL = "rm_auth.Tenant"
TENANT_DOMAIN_MODEL = "rm_auth.Domain"

AUTH_USER_MODEL = "rm_auth_tenant.User"

# The "system" sentinel actor RMAuditModel.save() falls back to as
# created_by/updated_by when no request-scoped AuditContext user exists.
AUDIT_SYSTEM_USERNAME = "system"

AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rm_auth_tenant.authentication.jwt_authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "EXCEPTION_HANDLER": "drf_base_app.error_handler.exceptions.custom_exception_handler",
    "DEFAULT_RENDERER_CLASSES": [
        "drf_base_app.rest_framework.renderers.RMJSONRenderer",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "rm_workflow API",
    "VERSION": "v1",
    "DESCRIPTION": (
        "Workflow definition persistence API -- Workspaces, Workflows, "
        "WorkflowVersions, and per-stage graph JSON. See "
        "docs/workflow-store-design.md."
    ),
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "APPEND_COMPONENTS": {
        "securitySchemes": {
            "Bearer": {
                "type": "apiKey",
                "name": "Authorization",
                "in": "header",
                "description": (
                    "JWT access token issued by rm_auth_tenant's "
                    "/api/rm_auth_tenant/login, sent as "
                    "'Bearer <access_token>'."
                ),
            }
        }
    },
    "SWAGGER_UI_SETTINGS": {
        "deepLinking": True,
        "persistAuthorization": True,
        "docExpansion": "list",
    },
    "REDOC_UI_SETTINGS": {
        "lazyRendering": False,
    },
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# rm_auth_tenant library configuration -- required by
# TenantResolutionMiddleware, SecurityContextMiddleware, and JWTAuthentication
# (all wired into MIDDLEWARE/REST_FRAMEWORK above). Mirrors rm_auth_tenant's
# own harness settings.py; see that file for the full key-by-key rationale.
# ---------------------------------------------------------------------------
# RM_AUTH = {
#     "JWT_ACCESS_TTL_SECONDS": int(os.environ.get("RM_AUTH_ACCESS_TTL", "900")),
#     "JWT_REFRESH_TTL_SECONDS": int(
#         os.environ.get("RM_AUTH_REFRESH_TTL", str(60 * 60 * 24 * 7))
#     ),
#     "DEFAULT_ALGORITHM": os.environ.get("RM_AUTH_DEFAULT_ALGORITHM", "HS256"),
#     "DEFAULT_SIGNING_SECRET": os.environ.get(
#         "RM_AUTH_HS256_SECRET", "dev-only-hs256-secret"
#     ),
#     "CASBIN_MODEL_PATH": str(RM_AUTH_TENANT_DIR / "policy" / "casbin_model.conf"),
#     "ENFORCER_CACHE_TTL_SECONDS": int(os.environ.get("RM_AUTH_ENFORCER_TTL", "300")),
#     "DEFAULT_TENANT_ID": get_default_tenant_id(),
#     "DEFAULT_PERSONA_NAME": get_default_persona_name(),
#     "SIGNUP_EMAIL_VERIFICATION_ENABLED": os.environ.get(
#         "RM_AUTH_SIGNUP_EMAIL_VERIFICATION_ENABLED", "false"
#     ).lower()
#     == "true",
#     "EMAIL_VERIFICATION_TTL_SECONDS": int(
#         os.environ.get("RM_AUTH_EMAIL_VERIFICATION_TTL", str(60 * 60 * 24 * 3))
#     ),
#     "EMAIL_VERIFICATION_URL": os.environ.get(
#         "RM_AUTH_EMAIL_VERIFICATION_URL",
#         "http://localhost:3000/verify-email?token={token}",
#     ),
# }

RM_AUTH_TENANT = {
    "CASBIN_MODEL_PATH": str(
        Path(__file__).resolve().parent.parent.parent
        / "rm_auth_tenant"
        / "rm_auth_tenant"
        / "policy"
        / "casbin_model.conf"
    )
}
