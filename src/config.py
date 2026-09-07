"""Configuración central de targets de la bridge API.

`MPRO_TARGET` decide contra qué instancia de SQL Server (mpro) corren todas
las extracciones de póliza/comprobante. Confirmado con Esteban 2026-09-07:

- `mssql_207` (TRIVASADB en BACK-MPRO) es la base "buena" / autoritativa.
- Mientras 207 está en desarrollo, se usa `mssql_205` (TRIVASADB3 en
  SVRMPRO) como sustituto temporal. Alcance de fechas mientras tanto:
  solo primer semestre 2026 (enero-junio) — 205 no se validó más allá de
  ese rango.

Cuando 207 vuelva a estar disponible, cambiar MPRO_TARGET aquí (un solo
lugar) revierte todo el pipeline sin tocar los extractores.
"""
MPRO_TARGET = "mssql_205"
