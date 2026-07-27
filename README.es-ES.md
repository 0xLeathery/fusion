# model-fusion

[![eval](https://github.com/0xLeathery/fusion/actions/workflows/eval.yml/badge.svg)](https://github.com/0xLeathery/fusion/actions/workflows/eval.yml)

Un **plugin** de Claude Code que implementa **auto-fusión (Mixture-of-Agents)** utilizando subagentes nativos, de modo que se ejecuta contra tu **suscripción** en lugar de una facturación de API por token.

Ante una tarea difícil, distribuye tu prompt a un pequeño panel de **subagentes de persona** que se ejecutan en paralelo —mismo modelo base, diferentes enfoques— y luego **sintetiza** sus borradores en una única respuesta auditada. Debido a que cada panelista se ejecuta en tu sesión de Claude Code, el costo se paga en **margen de límite de uso, no en dólares**.

## Por qué auto-fusión (proveedor único)

Los resultados publicados de Mixture-of-Agents y los propios datos de Fusion de OpenRouter sitúan aproximadamente **tres cuartas partes de la mejora en la *síntesis*** y cerca de **un cuarto en la *diversidad***. La auto-fusión de proveedor único mantiene deliberadamente el mismo modelo base y obtiene su diversidad a través de **personas distintas + muestreo** en lugar de otros proveedores, capturando así la mayor parte del beneficio mientras se mantiene en una sola suscripción.

El precio es el rendimiento: un **panel de N personas más la síntesis consume aproximadamente (N+1)× tokens por consulta**, por lo que alcanzarás el techo de tu suscripción semanal proporcionalmente más rápido. Ese intercambio —y el hecho de que una sesión limitada produce *cero* resultados, no una calidad inferior— es precisamente la razón por la cual el router tiene como valor predeterminado **selective**.

## Cómo funciona

1. Un **hook de router** `UserPromptSubmit` (o el comando `/fuse`) decide si un prompt merece ser fusionado.
2. La **habilidad `fusion`** despliega el panel de personas **en paralelo**, cada uno en la misma tarea, realizando cada uno una pasada independiente aumentada por herramientas.
3. La habilidad **sintetiza** los borradores con una rúbrica (libro de reclamaciones, verificación de errores correlacionados, resolución de contradicciones basada en evidencia, unión de cobertura, calibración, guardia anti-mayoría) y devuelve una respuesta fusionada **más** un bloque auditable de `Synthesis notes`.

## Componentes

| Ruta | Qué es |
|------|------------|
| `.claude-plugin/plugin.json` | Manifiesto del plugin (`model-fusion` v0.1.0). |
| `skills/fusion/SKILL.md` | Núcleo: orquestación + rúbrica de síntesis. |
| `agents/fusion-skeptic.md` | Persona — asume que la respuesta obvia es incorrecta; busca contraejemplos. |
| `agents/fusion-builder.md` | Persona — respuesta más completa, concreta y accionable. |
| `agents/fusion-analyst.md` | Persona — profundidad en el aspecto más crítico y fundamental. |
| `hooks/hooks.json` + `hooks/fusion-router.sh` | Router `UserPromptSubmit` filtrado por dificultad. |
| `commands/fuse.md` | `/fuse` — punto de entrada explícito que anula el hook. |
| `settings.json` | Configuración recomendada (establece `FUSION_MODE`). |

## Instalación

```bash
# Desde el directorio que contiene la carpeta de este plugin:
claude plugin validate ./model-fusion      # opcional: confirmar que está bien formado
claude plugin install ./model-fusion        # instalar desde una ruta local
```

(Si guardas el plugin bajo otro nombre de carpeta, apunta los comandos a esa ruta).

Una vez instalado, la habilidad `fusion`, el comando `/fuse`, los tres agentes de persona y el hook del router estarán disponibles en tus sesiones.

## Uso

- **Explícito:** `/fuse <tarea difícil>` siempre ejecuta el panel y la síntesis, independientemente de `FUSION_MODE`.
- **Automático:** con el router activado, un prompt de alta dificultad recibe un aviso para invocar la habilidad `fusion`.

### Modos — el interruptor `FUSION_MODE`

El router lee la variable de entorno `FUSION_MODE`:

| `FUSION_MODE` | Comportamiento |
|---------------|-----------|
| `off` | No-op. El router nunca inyecta nada. |
| `always` | Inyecta un recordatorio para fusionar en **cada** prompt. |
| `selective` | **(predeterminado)** Ejecuta una heurística económica sin llamada al modelo e inyecta solo cuando el prompt se califica como "difícil". |

La heurística (en `hooks/fusion-router.sh`) marca un prompt como difícil cuando ocurre **cualquiera** de lo siguiente: longitud del prompt superior a ~320 caracteres, dos o más signos de interrogación, o una palabra clave analítica (`analyse`/`analyze`, `compare`, `design`, `architecture`, `trade-off`, `evaluate`, `root cause`, `prove`, `why`). **No realiza ninguna llamada al modelo**.

**Predeterminado:** `selective` se aplica en el propio script del router, por lo que la fusión se mantiene desactivada para tareas sencillas incluso sin configuración. Para cambiarlo, establece la variable de entorno:

```bash
export FUSION_MODE=off        # silenciar el router
export FUSION_MODE=always     # sugerir en todo
```

…o copia el bloque `env` de `settings.json` incluido en tu propio `.claude/settings.json`. `/fuse` ignora `FUSION_MODE` por completo; siempre fusiona.

## Ajuste del equilibrio costo / calidad

- **Tamaño del panel.** Predeterminado **3**, rango **2–5**. El **salto de 1→2 borradores captura la mayor parte de la mejora de la síntesis**; un panel amplio en cada tarea es mayormente desperdicio. Usa 2 para peticiones concretas, reserva 4–5 para aquellas genuinamente polifacéticas.
- **Palanca de presupuesto — modelo.** Las personas usan **Opus** por defecto. Cámbialas a **Sonnet** (edita `model: opus` → `model: sonnet` en los tres archivos bajo `agents/`) para reducir el consumo sustancialmente a costa de algo de calidad.
- **Modo.** Mantén `selective` (o `off`) para el trabajo rutinario; `always` consumirá tu techo semanal rápidamente.

## Benchmarking

No aceptes la afirmación de calidad por fe; `eval/` la pone a prueba. La idea clave: el punto de referencia honesto no es una sola pasada, sino la **autoconsistencia de presupuesto igual** (gastar los mismos (N+1)× tokens extrayendo más muestras del mismo modelo y votando). La fusión debe superar *eso* para justificarse.

- `eval/router/` — puntúa la heurística de enrutamiento (precisión/recall/F1) frente a un conjunto de prompts etiquetados. Determinista, sin API, ejecutable ahora:
  `python3 eval/router/run_router_eval.py`
- `eval/quality/` — impulsa ejecuciones sin interfaz (headless) a través de `single` / `selfconsist:N` / `fusion:N`, califica objetivamente y reporta IC de precisión, significancia de McNemar y ratios de tokens. Comienza con `--dry-run` para probar el flujo sin gastar presupuesto.

Consulta `eval/README.md` para ver la metodología completa, ablaciones y advertencias.

### Línea base publicada

La línea base se publica en dos niveles; consulta **`eval/BASELINE.md`**:

- **Router (determinista, filtrado).** Números congelados (actualmente **F1 0.914**, n=36) con un filtro de IC (`--min-f1 0.90`) que falla la compilación ante una regresión de enrutamiento. Este es el check verde de arriba.
- **Calidad (instantánea comprometida).** Las llamadas reales al modelo son demasiado costosas/ruidosas para CI y el panel de fusión necesita un agente headless que omita permisos, por lo que la afirmación de calidad se publica como una instantánea generada por humanos en un conjunto de datos objetivo real (no el `sample.jsonl` que es solo para plomería), con el resumen de McNemar / IC / ratio de tokens comprometido junto a ella. La afirmación principal "+X puntos frente a la línea base honesta" reside en **[`RESULTS.md`](RESULTS.md)** y es generada por código mediante `metrics.py --headline` para que no diverja de los datos. *(Estado: pendiente de la primera medición real; aún no se reclama mejora de calidad).*

## Limitaciones

- **Consumo de tokens.** ≈ (N+1)× tokens por consulta fusionada. Planifica según el techo de tu suscripción semanal.
- **Límite de concurrencia.** Claude Code limita cuántos subagentes se ejecutan en paralelo; los tamaños de panel de 2–5 se mantienen dentro de este límite.
- **Sin recursión.** Los subagentes no pueden generar sus propios subagentes, por lo que toda la expansión ocurre en el agente principal: los panelistas ejecutan su pasada y regresan.
