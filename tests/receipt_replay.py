"""Freeze recorded runtime metadata while replaying exact model requests."""
from unittest.mock import patch


def recorded_sqlite_metadata(evidence):
    versions = set()

    def visit(value):
        if isinstance(value, dict):
            if 'sqlite_version' in value:
                versions.add(value['sqlite_version'])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(evidence)
    if len(versions) != 1:
        raise ValueError('Replay requires one recorded SQLite metadata version')
    # This changes only the reported string, not SQLite or FTS execution. Tests
    # still compare every retrieved passage, score, prompt and request hash.
    return patch('sqlite3.sqlite_version', versions.pop())
