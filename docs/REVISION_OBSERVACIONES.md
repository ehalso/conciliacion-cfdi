# Revisión de observaciones (Ismael ene-2026, Roberto sep-2026)

> **Documentación provisional, local a la rama `fix-agrupar-cargo-abono`.**
> Cuando se termine de revisar todas las correcciones, se documenta de forma definitiva en `trivasa-context` y este archivo se retira o se reduce a un enlace.

## Principio de fuentes (no mezclar)

Cada columna del reporte sale de una sola fuente; no se rellena un campo de una fuente con otra.

| Fuente | Qué es | Bloque del reporte |
|---|---|---|
| A. Registro Mpro | Folios y tablas de Mpro (proveedor, montos, pólizas, pagos) | Registro, Póliza, Pago |
| B. XML adjunto en Mpro | `Comprobante_Digital` | Comprobante XML (`XML_*`) |
| C. BD SAT | Postgres `raw_sat_api.cfdi` | Base de datos SAT (`SAT_*`) y Conciliación (`CONC_*`) |

Ejemplo: el Uso de CFDI de 23-0008989 queda vacío en el bloque XML porque el XML de Mpro no lo trae; el valor del SAT (G03) debe mostrarse en el bloque SAT, no en el XML.

## Observaciones de Ismael (enero 2026)

| # | Estado | Nota |
|---|---|---|
| 1, 2, 4 | Resuelto | Commits `66aa165` y `8489da3`. |
| 3 | Solo visual | `Tipo Póliza` ahora muestra nombre (1 Ingreso, 2 Egreso, 3 Diario). El reporte solo trae pólizas tipo 3 (Diario); falta confirmar con Ismael si quiere pólizas de egreso/cheque. |

## Observaciones de Roberto (septiembre 2026)

### Roberto 3 — complementos de pago (commit `66aa165`)
`COMPLEMENTO_PAGO` traía el UUID de la propia factura (`Pago_Cxp_Comprobante`). Ahora es el UUID del CFDI tipo P real, ligado por el UUID de la factura vía `ZTRV_Comprobante_Digital_Pago`. Folios de prueba: 07-0011828 y 05-0032357.

### Roberto 1 — método de pago vacío en 23-0008989 (sin commit al momento de escribir esto)
- Causa: el `COALESCE` original tomaba `Cd_Metdo_Pago_CFDI` aunque viniera `''` (los vacíos no son NULL), así que nunca caía a la otra columna.
- Las dos columnas NO son equivalentes: `Cd_Metdo_Pago_CFDI` guarda el método (PUE/PPD); `Cd_Metodo_Pago` en registros nuevos guarda la forma de pago SAT (01, 03, 99) y en registros antiguos el método (PPD/PUE). También hay basura (`EFECTIVO`, `NA`, `No identificado`).
- Corrección (`sql.py`, `XML_SQL` y `GASTO_XML_DOCUMENTO_SQL`): método = `Cd_Metdo_Pago_CFDI` si es PUE/PPD; si no, `Cd_Metodo_Pago` solo si es PUE/PPD; en otro caso vacío. Nunca se toma un código de forma de pago como método. Forma de pago sigue saliendo de `Cd_Forma_Pago`.
- Resultado: 23-0008989 muestra PPD y "99 - Por definir". Septiembre: método solo PPD/PUE/VARIOS.
- Uso de CFDI sigue vacío (fuente B no lo trae). **Decisión pendiente**: agregar Uso CFDI, Método y Forma de pago al bloque SAT.

### Roberto 2 — póliza que no aparecía en 23-0008836
- Causa: la póliza (504996/505023) existe, pero todas sus líneas caían en los filtros de `DOC_POLIZA_SQL` (`Pd_Importe=0`, cuentas 10500/10600, y 1170/2110/2150 en Compra/Indirecto/CxP, más 2130 en CxP). Sin líneas, el documento perdía la póliza.
- Corrección: `DOC_POLIZA_SIN_LINEAS_SQL` (`sql.py`) trae las pólizas ligadas por `Poliza_Control` cuyas líneas fueron filtradas; `construir_tipo` (`documentos.py`) las agrega con cargo 0 solo para folios sin póliza.
- Efecto en septiembre: 11,330 a 11,387 filas; cargo total sin cambio ($70,935,168.97); compras sin póliza 45 a 32.
- Nota: la pantalla de Mpro (`RPCT001D.asp`) muestra todas las líneas de la póliza sin esos filtros. Pendiente decidir si se muestran también.

## Hallazgo: 32 CxP libre sin póliza (septiembre 2026)

No es un error del reporte. Mpro busca la póliza igual que el reporte: `POLIZA_REDIRDOC.asp` consulta `Poliza_Control` por `Pc_Tabla`, `Pc_Documento` y `Es_Cve_Estado<>'CA'`. Las CxP no tienen enlace "Ver póliza" en `RPCXP`.

Las pólizas de CxP libre las genera la config `0380` (nacional 2020 en adelante; hermanas 0267 extranjero y 0285 importes negativos), con `INNER JOIN Concepto_Cxp`. Condiciones de la 0380: estado distinto de `CA`, concepto fuera de `0023/0024/0025/0034/0038/0039/0040`, tipo de proveedor distinto de `00`, fecha desde 2020-12-01, importe neto >= 0.

- 31 de las 32 tienen `Cxp_Concepto` vacío (casi todas del proveedor `0000000021`): el `INNER JOIN` las descarta.
- 1 tiene concepto `0023` (carga de glosa FONACOT), excluido por la config.
- Las 24 con póliza tienen concepto 0016 o 0017 y entran en la póliza consolidada "CUENTA ORDEN CXP LIBRE DEL <fecha>" (generadas el 1 de octubre).
- En ene-sep 2026 son 329 CxP libres sin póliza (320 del proveedor `0000000021`, 9 del concepto 0023).

Pendiente: preguntar a Contabilidad si es intencional que se capturen sin concepto.

## Limitación conocida: póliza consolidada de varios documentos de gasto

En un folio de Registro de gasto con varios documentos (`DOC_ID`), Mpro puede generar una sola línea de póliza que suma varios documentos del mismo proveedor/cuenta (se enlaza por `Pd_Referencia`). El reporte no puede repartir esa línea entre los documentos: queda con `DOC_ID = VARIOS` y proveedor, UUID, RFC, método y forma de pago en "VARIOS"; los documentos individuales aparecen aparte con cargo 0.

Ejemplo (septiembre 2026): folio `01-0038228`, póliza `0000506826`. Cuatro XML (documentos 0001 a 0004). Los documentos 0003 ($70,123.15) y 0004 ($32,320.09) tienen línea propia; los 0001 ($43,687.61) y 0002 ($44,235.15) quedan en una línea "VARIOS" de cargo $75,795.48 (TOTAL $87,922.76 = 43,687.61 + 44,235.15). Otros: `05-0199975` (2 XML de $532,000, una línea de $1,064,000), `01-0038372`, `01-0038467`, `01-0038468`, `01-0038500`, `01-0038697` (varios XML de $0.01, una línea).

Alcance en septiembre: 35 folios con "VARIOS" (16 Registro de gasto, 19 nómina). Los de nómina y varios de gasto no tienen XML en Mpro; ahí el "VARIOS" es solo la línea de póliza sin atribuir, no varios XML. No se encontraron falsos positivos del `LIKE FOLIO+'%'`.

### Por qué sale "VARIOS" (septiembre 2026: 270 líneas en 35 folios; todos de gasto)

`atribucion.py` asigna cada línea de póliza a un documento por (folio, CECO, importe). Queda `VARIOS` en dos situaciones:

1. **Póliza consolidada (la línea no coincide con ningún documento):** el importe de la línea no iguala el de un documento individual; mezcla varios. 30 folios.
   - Con XML (6): `01-0038222`, `01-0038228`, `01-0038234`, `01-0038565`, `01-0038566`, `05-0199975`.
   - Sin XML en Mpro (24): los 19 de nómina más `01-0038624`, `01-0038631`, `01-0038718`, `01-0038864` (175 líneas, 8 documentos) y `05-0200941`.
2. **Importes idénticos entre documentos (no es consolidada):** cada documento tiene su línea, pero los importes coinciden (p. ej. varios de $0.01) y, como cada uno tiene UUID distinto, no se sabe cuál es de cuál. 5 folios: `01-0038372`, `01-0038467`, `01-0038468`, `01-0038500`, `01-0038697` (22 líneas).

Hallazgo: en los 35 folios todos los documentos tienen el mismo proveedor (clave de proveedor única por folio). Aun así el reporte pone `VARIOS` en proveedor, RFC y nombre. Solo UUID/XML es realmente ambiguo; el proveedor podría mostrarse. Esto atiende la preocupación sobre proveedor y campos relacionados.

Propuesta (no implementada, no solicitada): en `_por_documento`, si todos los documentos del folio comparten proveedor, mostrar ese proveedor en vez de `VARIOS`; y distinguir en UUID "VARIOS (póliza consolidada)" de "sin XML" (vacío).

### Corrección de la atribución: suma por (folio, CECO, documento)

Causa de buena parte de los `VARIOS`: la póliza trae una línea por (cuenta, CECO) con **todo lo que el documento reparte en ese CECO sumado**, pero la atribución comparaba contra cada renglón individual de `Gasto_Registro_Control`. Ejemplo `01-0038624`: las 23 líneas en `VARIOS` coincidían exacto con la suma de un solo documento en su CECO (no eran impuestos; el folio no tiene IVA).

Cambio en `atribucion.py`: se compara el importe de la línea contra la suma por (FOLIO, CECO, Grd_ID). Se probaron tres métodos en septiembre y enero de 2026:

| Método | Sep: VARIOS (folios) | Ene: VARIOS (folios) |
|---|---|---|
| Renglón (anterior) | 270 (35) | 261 (28) |
| Renglón y, si no coincide, suma | 49 (32) | 44 (25) |
| Solo suma (adoptado) | 49 (32) | 44 (25) |

Renglón+suma y solo suma difieren en 1 línea (enero, `01-0035004`, línea de 101.83 en CECO 000135: el documento 0005 coincide exacto y el 0004 solo por tolerancia de 0.01; ambos con misma firma). Ninguna línea que ya se atribuía por renglón pasó a `VARIOS`. Tiempos equivalentes (~50 s). Se adoptó solo suma por ser más simple y exacta.

`VARIOS` que quedan en septiembre (49 líneas): 22 por importes idénticos entre documentos (5 folios), 10 por línea que suma varios documentos (póliza consolidada real) y 17 de nómina (`GASTO_REGISTRO_NOMINA`) cuya suma tampoco coincide; esas 17 quedan por revisar.

## Pendientes por revisar: anomalías de XML en gasto (septiembre 2026)

No corregidas; falta decidir con quien captura/Contabilidad.

1. `01-0038565` y `01-0038566` tienen el mismo UUID (`77AACD00-5206-4F58-83B9-6AC7B698B298`, $389,919.54) adjunto en dos folios distintos (dos documentos cada uno), y sus totales son $157,589.90 y $139,674.92. Parece un XML adjuntado de más o a otro folio.
2. `01-0038222` tiene el mismo UUID (`43BEB877-F7D3-4405-8974-8BB329713B88`, $66,917.40) adjunto dos veces (documentos 0001 y 0002); el total del folio es $66,917.40.

## Auditoría de fuentes: pendientes (no implementados, aún no solicitados)

1. Retenciones que pisan campos del XML: excluir `RETENCIONES` del CTE `xml` y usar columnas propias.
2. `NUMERO_FACTURA` viene del XML pero está agrupada en "Registro".
3. Proveedor representativo en gasto sin `DOC_ID` (3,388 folios con varios proveedores): poner `VARIOS` o usar `PROVEEDOR_MULTIPLE`.
4. XML sin `DOC_ID` se aplica a todo el folio.
5. `CONCEPTO_GASTO` por documento se calcula y se descarta.
6. `astype(str)` en RFC y `CLAVE_PROVEEDOR`.
7. XML ligado por `LIKE FOLIO+'%'`.
8. Falta conciliar RFC (`XML_RFC_EMISOR` y `RFC_PROVEEDOR` contra `SAT_RFC`).

## Otros pendientes abiertos

- Confirmar con Ismael si quiere pólizas de egreso/cheque.
- Definir cómo marcar facturas PPD sin complemento; revisar las 27 facturas PUE de enero que sí traen complemento real.
- Confirmar que `ZTRV_Comprobante_Digital_Pago` esté actualizada.
- Validar las 270 líneas `VARIOS` de septiembre y la limitación de retenciones en folios multi-documento.
- Definir "No localizados" y confirmar la tolerancia de 0.05.
- Decidir si los CFDI EMITIDO autoemitidos entran como "Solo SAT".
- Rotar la credencial admin de Postgres.

## Referencia operativa

- Mpro SQL Server `.207` (TRIVASADB; la `.205` está caída). Los ASP de Mpro están en `.200` (montaje `/mnt/win200_c`; skill `mpro-reporte-asp`).
- Pruebas: `python3 -m unittest discover -s tests` (27 OK).
