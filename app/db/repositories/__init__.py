"""Synchronous data-access repositories, one module per table.

Each function takes a ``sqlite3.Connection`` (injected by the caller), runs one
transaction per write, and returns plain ``dict`` rows. No global connection.
"""
