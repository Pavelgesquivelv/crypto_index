# Selección anticipada de la muestra

Regla para los próximos cierres (primer cierre previsto: 2026-09-30).
El histórico existente no se recalcula.

- Rebalanceo: último día natural del mes, con precios de las 07:00 CDMX.
- Selección: día anterior al rebalanceo que sea lunes a viernes, a las 07:00 CDMX.
  No se descuentan festivos. La ventana de captura termina a las 07:15.
- Se fijan los activos y sus pares con la captura anticipada. No se vuelve a
  elegir el ranking al rebalancear. Los precios y cantidades se calculan al cierre.
- Una identidad desconocida o una ruta pendiente de revisión bloquea la selección.
  El informe original queda guardado. La revisión debe hacerse sobre esa evidencia;
  no se debe eliminar el informe para reemplazarlo por un ranking posterior.
- Un fallo de precio al cierre detiene la publicación; no se sustituye un activo
  silenciosamente ni se interpreta el error como indisponibilidad.
- La fase `capture` sin `--cutoff` puede invocarse diariamente: en días distintos
  del programado no consulta proveedores ni escribe archivos.

Ejemplos:

| Rebalanceo | Selección |
|---|---|
| Miércoles 2026-09-30 | Martes 2026-09-29 |
| Sábado 2026-10-31 | Viernes 2026-10-30 |
| Domingo 2026-05-31 | Viernes 2026-05-29 |
| Lunes 2026-08-31 | Viernes 2026-08-28 |

## Migración en el servidor

Actualizar el código antes del día de selección. El servicio existente de captura
ya ejecuta `scripts/monthly_cycle.py capture`; no cambia ese comando.

Cambiar el calendario del temporizador mediante un drop-in:

```ini
# /etc/systemd/system/crypto-index-capture.timer.d/schedule.conf
[Timer]
OnCalendar=
OnCalendar=*-*-* 07:00:00 America/Mexico_City
Persistent=false
```

Recargar systemd y reiniciar únicamente `crypto-index-capture.timer`. La lista de
temporizadores mostrará una comprobación diaria, aunque el script solo captura
en el día laborable previo. No cambiar los temporizadores diario, mensual ni del
dashboard. El servicio de cierre sigue a las 07:04 del último día del mes.

Los reportes nuevos registran `selection_policy=previous_weekday_v1`,
`selection_date` y `rebalance_date`. La validación exige estos campos y comprueba
las fechas de recepción de ambas fuentes contra la ventana anticipada.
