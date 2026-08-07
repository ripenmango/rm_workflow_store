# RM Platform Plugin Architecture

## Vision

RM Platform is an enterprise operating system, not just a workflow
engine. The platform should support runtime extensibility through
plugins while keeping the core stable.

Core capabilities: - Authentication & RBAC - Multi-tenancy - Workflow
Engine - Event Bus - Scheduler - Plugin Marketplace - Connector
Framework - Business Modules - AI Extensions

## Recommended Architecture

``` text
                    RM Platform

        +------------------------------------+
        |         Django Platform Kernel     |
        +------------------------------------+
        | Authentication                     |
        | Multi-Tenancy                      |
        | RBAC                               |
        | REST API                           |
        | Workflow Engine                    |
        | Scheduler                          |
        | Event Bus                          |
        | Plugin Registry                    |
        | Audit                              |
        +----------------+-------------------+
                         |
                  Plugin Runtime
                         |
       +-----------------+------------------+
       |                 |                  |
 Connector          Business          AI/UI
 Plugins            Plugins           Plugins
```

## Keep Django for the Platform Kernel

Use Django + DRF for: - Authentication - User Management -
Multi-tenancy - RBAC - REST APIs - Workflow Definitions - Plugin
Registry - Configuration - Audit Logging - Administration

Do **not** implement plugins as Django apps in `INSTALLED_APPS`.

## Plugin Packaging

Each plugin is a plain Python package:

``` text
transport_plugin.zip

manifest.yaml
plugin.py
operations/
assets/
forms/
```

Load plugins dynamically using `importlib`.

## Plugin Categories

### Connector Plugins

Examples: - Email - Slack - Teams - WhatsApp - HTTP - Kafka - RabbitMQ -
S3 - SAP - Salesforce

### Business Plugins

Examples: - Storage - Transport - Workshop - Fleet - Billing - Inventory

### AI Plugins

-   OCR
-   Classification
-   Translation
-   Summarization
-   Prediction

### UI Plugins

-   Forms
-   Dashboards
-   Reports
-   Widgets
-   Menus

## Plugin SDK

``` python
class RMPlugin:

    def manifest(self):
        ...

    def initialize(self):
        ...

    def operations(self):
        ...

    def permissions(self):
        ...

    def events(self):
        ...

    def forms(self):
        ...

    def execute(self, operation, context):
        ...
```

The workflow engine only knows: - Plugin - Operation - Inputs - Outputs

## Manifest

``` yaml
id: email
version: 1.0

operations:
  - send_email

permissions:
  - email.send

events:
  - email.received
```

## Event Driven Communication

Plugins publish and subscribe to events rather than calling each other
directly.

Example:

Transport -\> shipment.created -\> Storage -\> Billing -\> Notification

## Plugin Runtime

The Django application should not execute plugin code directly.

``` text
Workflow Engine
      |
Plugin Runtime
      |
Plugin
      |
Result
```

Initially this runtime can be an in-process Python loader using
`importlib`. Later it can evolve into isolated worker processes.

## Data Strategy

Core entities: - User - Tenant - Role - Permission - Workflow

Plugin-specific configuration: - PostgreSQL JSONB - Metadata-driven
entities

Avoid dynamic Django model registration.

## Marketplace

``` text
Upload ZIP
    ↓
Validate
    ↓
Install
    ↓
Register
    ↓
Enable
```

## Technology Stack

  Component         Recommendation
  ----------------- ----------------------------------
  Platform Kernel   Django + DRF
  Plugin SDK        Pure Python
  Plugin Runtime    Python + importlib
  Workflow Engine   Python
  Event Bus         Redis Streams / RabbitMQ / Kafka
  Database          PostgreSQL + JSONB
  Scheduler         Celery
  AI                Python

## Roadmap

### Phase 1

-   Platform Kernel
-   Authentication
-   RBAC
-   Workflow
-   Plugin Registry

### Phase 2

-   Plugin SDK
-   Manifest
-   Dynamic Loading
-   Configuration

### Phase 3

-   Connector Plugins

### Phase 4

-   Business Plugins

### Phase 5

-   Marketplace

### Phase 6

-   Isolated Plugin Runtime

## Final Recommendation

Keep Django as the platform kernel and build plugins as plain Python
packages with: - Manifest-driven registration - Runtime discovery using
`importlib` - Standard `execute()` contract - Event-driven
communication - PostgreSQL JSONB for flexible metadata

This architecture provides runtime extensibility while preserving
Django's strengths and avoiding its runtime limitations.
