"""Yandex Forms export schema used by the local importer."""

FORM_FIELD_ORDER = ("policy", "name", "email", "images")
MAX_REFERENCE_IMAGES = 3
TRUTHY_POLICY_VALUES = {"1", "true", "yes", "y", "on", "accepted", "checked", "да"}
