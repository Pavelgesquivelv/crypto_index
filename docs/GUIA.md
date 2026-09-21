# Guía local — Crypto Index Rebalancer

## 1. Qué vamos a construir

Un generador de composición mensual: toma las primeras 15 criptomonedas elegibles de CoinMarketCap y selecciona las primeras diez disponibles en Binance Spot. Cada una recibe un peso objetivo de 10%; las posiciones no cubiertas se conservan en USDT. Esta versión genera una propuesta y evidencia, sin ejecutar compras.

El top 15 se calcula **después** de excluir stablecoins, memecoins y tokens envueltos o vinculados a otros activos. Por tanto, puede llegar más allá del puesto 15 del ranking global.

## 2. Preparar el entorno de Windows

Abre PowerShell en la carpeta del proyecto. Comprueba primero que tienes Python 3.11 o posterior:

```powershell
py -3 --version
```

Si no se reconoce `py`, necesitamos localizar o instalar Python antes de continuar. Si funciona, crea un entorno exclusivo del proyecto:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Usar el ejecutable del entorno directamente evita cambiar la política de ejecución de PowerShell. La instalación puede requerir conexión a Internet. No se necesita ninguna clave de Binance.

## 3. Probar las reglas sin descargar datos

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

El resultado esperado es `OK`. Las pruebas usan datos ficticios: exclusiones, mercados suspendidos, límite del universo, efectivo, identidades desconocidas, duplicados, datos antiguos y calendario. No demuestran rentabilidad ni sustituyen una prueba de integración con los proveedores.

## 4. Generar una composición con datos actuales

```powershell
.\.venv\Scripts\python.exe -m crypto_index.cli
```

La consola muestra el estado y la ruta a `report.json`. Abre ese archivo y `portfolio.csv` dentro de la nueva carpeta de `runs`. No esperes siempre las mismas monedas: la composición depende del ranking y la disponibilidad al ejecutar.

Revisaremos juntos:

1. Fecha real de captura y versión del registro utilizado.
2. Exclusiones y sus motivos.
3. Los 15 integrantes del universo elegible y su orden.
4. Disponibilidad de cada activo y pares directos USDT.
5. Composición final, ausencia de duplicados y suma de pesos de 100%.
6. USDT residual si hay menos de diez disponibles.

Si aparece `review_required`, busca el identificador CMC señalado. Antes de actualizar `config/assets.json`, verifica su naturaleza y que el activo de Binance corresponda al mismo proyecto. Registra `symbol`, `binance_base`, `classification` y `reviewed_on`. Usa `classification: excluded` para una exclusión revisada. No marques automáticamente como elegible un activo desconocido.

Si aparece `route_review_required`, existe un mercado Spot activo pero falta un par directo contra USDT para una moneda seleccionada. El script detiene la propuesta hasta definir la ruta; no modifica la metodología saltándose esa moneda.

## 5. Calendario y límites operativos

Fecha objetivo: último día calendario mensual, 07:00, zona `America/Mexico_City`.

```powershell
.\.venv\Scripts\python.exe -m crypto_index.cli --scheduled
```

El modo acepta ejecuciones de 07:00 a 07:14 para reintentos. Fuera de esa ventana termina sin descargar datos. **No instala una tarea ni permanece esperando.** Programarlo en un servidor será un paso posterior. La fecha de captura queda registrada; una ejecución tardía no representa retrospectivamente las 07:00.

El informe mensual existente se conserva. Si requiere revisión, primero guarda esa carpeta como evidencia bajo otro nombre, corrige el registro y vuelve a ejecutar dentro de la ventana. Fuera de ella, usa una previsualización y documenta que se perdió el corte mensual. No borres ni sobrescribas evidencia para simular un corte puntual.

Un archivo `.lock` impide ejecuciones simultáneas para el mismo período. Si hubo una interrupción y permanece un bloqueo, comprueba que el proceso terminó antes de retirar exclusivamente ese archivo. Los fallos previos al informe final pueden dejar capturas parciales, que deben conservarse aparte antes de reintentar si se necesitan para auditoría.

## 6. Qué significa viabilidad en esta etapa

Se comprueban mercado activo y permiso Spot del catálogo público, y se guardan los filtros publicados por Binance. Todavía no se validan permisos de tu cuenta, tamaño mínimo de orden para un capital específico, saldos, liquidez, comisiones ni deslizamiento. `composition_ready` no equivale a autorización o viabilidad completa de ejecución.

La clasificación combina etiquetas de CoinMarketCap y revisión por identidad. No pretende identificar automáticamente todos los posibles derivados o activos vinculados. Un activo nuevo sin revisar bloquea la composición en lugar de alterar silenciosamente el universo.

## 7. Preparación de GitHub — etapa posterior

Repositorio previsto: `pavelgesquivelv/crypto-index-rebalancer`, público. Tú crearás el repositorio y revisaremos el contenido antes de subirlo.

Se compartirán código, documentación, configuración revisada y pruebas. `.gitignore` excluye `runs/`, `.venv/`, `.env`, cachés y registros locales. No guardes contraseñas o claves en el registro de activos. No se ha elegido una licencia de redistribución todavía; la decidiremos antes de publicar.

La configuración de GitHub Actions ya está preparada para ejecutar pruebas en Windows y Linux cuando lleguemos a esa etapa. Su existencia local no implica que las pruebas hayan corrido en GitHub.
