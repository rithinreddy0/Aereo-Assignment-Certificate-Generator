"""Adapt the existing parameterized persistence queries to Psycopg."""

import sqlite3

import psycopg


class Row(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def hybrid_row(cursor):
    columns = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: Row(zip(columns, values, strict=True))


class Connection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, query, params=()):
        try:
            return self.raw.execute(query.replace("?", "%s"), params)
        except psycopg.IntegrityError as exc:
            raise sqlite3.IntegrityError("Database constraint violation") from exc

    def executemany(self, query, params):
        try:
            with self.raw.cursor() as cursor:
                cursor.executemany(query.replace("?", "%s"), params)
        except psycopg.IntegrityError as exc:
            raise sqlite3.IntegrityError("Database constraint violation") from exc
