# My Harness (español)

My Harness es una aplicación local que ejecuta un harness de desarrollo con agentes de IA sobre tus propios
repositorios Git. Un agente **revisor** planifica y revisa en solo lectura; un agente **ejecutor** es el único que
escribe. El harness valida cada cambio con los comandos de tu proyecto, liga la revisión al contenido exacto y hace él
mismo el commit. El trabajo se organiza en fases y tareas acotadas, con documentación del proyecto, chat, métricas y
recuperación tras caídas. Todo corre en tu máquina: el servicio solo escucha en `127.0.0.1` y los modelos se usan a
través de las CLI oficiales de Codex y Claude Code con tu propia cuenta.

La documentación de referencia está en inglés: el [README](README.md) explica la instalación, la configuración, el
primer uso y la operación paso a paso. Esta página resume lo esencial y enlaza cada apartado.

## Estado

Versión previa a 1.0: la primera versión local está completa en el alcance declarado, el
paquete declara `0.1.9`, noveno parche de la primera versión pública `0.1.0`, y no está en PyPI ([changelog](CHANGELOG.md)).
Solo se ha probado en macOS ARM64. El recorrido guiado se comprueba desde el wheel instalado con clientes y
herramientas falsos, Git/SQLite temporales, configuración inicial en navegador y operaciones de proyecto por HTTP
protegido. La QA visual en/es se registra con límites propios; no acredita proveedores nuevos.
Licencia [MIT](LICENSE). Detalle en
[Status](README.md#status) y [Supported scope and limits](README.md#supported-scope-and-limits).

## Dos formas de empezar un proyecto

- **Crear un proyecto nuevo desde cero**: eliges en la interfaz una carpeta de proyectos, das nombre al proyecto y
  conversas con el revisor a partir de un brief; aceptas los documentos y el harness hace el commit raíz. Con una
  receta (Django o TypeScript web), una preparación confirmada crea después el entorno y el andamiaje técnico.
- **Incorporar un repositorio existente sin harness**: registras un checkout Git con al menos un commit y sin
  documentos de harness; el harness inventaría su árbol sin ejecutar código, el revisor redacta la documentación y
  una propuesta de perfil, y tú confirmas el commit documental que adopta la fase `P001`.

En ambas conversaciones respondes cada pregunta del revisor en su propio campo y envías una, una selección o todas
en un único turno; el panel lateral de tareas, runs, chat y conversaciones muestra en vivo lo que hace el agente.

[Más detalle](README.md#two-ways-to-start-a-project).

## Instalación

Elige **una** de las dos vías. Las dos dejan el mismo servicio instalado. El instalador crea su propio entorno
virtual (nunca tienes que crear ni activar uno), lo guarda todo fuera de tus checkouts Git y no cambia la
configuración de tu shell, de Git ni de los proveedores.

| | Desde el código fuente (clon Git) | Desde un paquete publicado |
|---|---|---|
| Qué descargas | Este repositorio | `my-harness-<versión>-distribution.tar.gz` de la página **Releases** del repositorio en GitHub |
| Herramientas | Python 3.14, uv 0.12.19, Git, Node 24.15.0 y npm 11.12.1 | Python 3.14, uv 0.12.19 y Git |
| Qué hace el instalador | Construye el paquete (un wheel con la UI compilada), lo verifica y lo instala | Comprueba los checksums del paquete ya construido y lo instala |

### 1. Comprueba las herramientas

```sh
python3.14 --version   # Python 3.14.x
uv --version           # uv 0.12.19
git --version
node --version         # v24.15.0  (solo para instalar desde el código fuente)
npm --version          # 11.12.1   (solo para instalar desde el código fuente)
```

El instalador nunca descarga estas herramientas. **uv** crea el entorno aislado e instala las dependencias Python
fijadas. Si `python3.14` o `uv` no están en tu `PATH`, añade `--python /ruta/absoluta/python3.14` o
`--uv /ruta/absoluta/uv` al comando de instalación.

### 2a. Instalar desde el código fuente

```sh
git clone https://github.com/AcostaDDev/my-harness.git
cd my-harness
scripts/install --allow-network
```

### 2b. Instalar desde un paquete publicado

Descarga `my-harness-0.1.9-distribution.tar.gz` y su `.sha256` de la
[página Releases](https://github.com/AcostaDDev/my-harness/releases) (o con `curl` como abajo) en la misma carpeta y ejecuta:

```sh
curl -LO https://github.com/AcostaDDev/my-harness/releases/download/v0.1.9/my-harness-0.1.9-distribution.tar.gz
curl -LO https://github.com/AcostaDDev/my-harness/releases/download/v0.1.9/my-harness-0.1.9-distribution.tar.gz.sha256
shasum -a 256 -c my-harness-0.1.9-distribution.tar.gz.sha256
tar -xzf my-harness-0.1.9-distribution.tar.gz
cd my-harness-0.1.9
scripts/install --dist "$PWD" --allow-network
```

El archivo contiene el wheel (con la UI compilada), el sdist, `pylock.toml`, `distribution-1.json`, `SHA256SUMS`
y `scripts/`. El instalador comprueba cada archivo; no necesita Node/npm ni el código fuente. El checksum prueba
que la descarga está íntegra, no quién la hizo: descárgalo solo del repositorio oficial.

### Qué hace el instalador

La primera instalación necesita **`--allow-network`** para descargar las dependencias fijadas en la caché.
Después, `scripts/install` sin opciones funciona sin red: verifica y reutiliza la instalación. Sin
`--allow-network`, una primera instalación falla porque la caché todavía está vacía.

Publica la instalación solo tras una comprobación aislada con agentes falsos (no llama a ningún modelo). Por
defecto usa `~/Library/Application Support/My Harness/` (`installation`, `data` y `configuration`) y la caché
`~/Library/Caches/My Harness`. Para elegir otras ubicaciones usa `--install-dir`, `--data-dir`, `--config-dir`
y `--cache-dir` con rutas absolutas fuera de todo checkout (entre comillas si tienen espacios), y el mismo
`--install-dir` después en `scripts/start`. Si una instalación falla queda como FAILED con su diagnóstico y no se
publica: consérvala y reintenta con directorios nuevos, sin borrar locks ni datos a mano.
[Tabla de directorios y opciones](README.md#what-the-installer-does).

## Primer uso

1. **Arranca el servicio** desde la carpeta donde ejecutaste el instalador (el clon o el paquete extraído):

   ```sh
   scripts/start
   ```

   Añade `--install-dir` si elegiste otro directorio de instalación, o `--port` para usar un puerto distinto de 8013.
   Verifica la instalación, crea la base de datos solo si no existe y sirve la UI/API, sin Node/Vite.
2. **Copia la clave de acceso.** El servicio muestra `My Harness: access key at <ruta>`. En otra terminal:

   ```sh
   pbcopy < '<ruta mostrada por el servicio>'
   ```

3. **Abre la UI.** Escribe `http://127.0.0.1:8013` en la barra de direcciones y pega la clave. La sesión dura
   ocho horas; cada arranque crea una clave nueva que se borra al parar.
4. **Configura.** Sin configuración la UI abre `/setup`: identidad Git, clientes/PATH/USER, modelo/esfuerzo del
   revisor, raíces autorizadas y supervisor. Buscar clientes sugiere rutas; comprobar versión/ayuda no llama a
   modelos. Inicia sesión en `codex`/`claude` fuera del harness y no pegues credenciales. Valida, revisa el diff
   y confirma **guardar**; después revisa y confirma **activar**. La vista previa comprueba los clientes y los
   proyectos registrados y señala qué corregir; el servicio aplica el cambio sin reiniciar ni pedir otra clave, al
   momento o, si hay trabajo en curso, **cuando termine** ese trabajo. Guardar no activa.
   [Primer arranque](README.md#first-run), [configuración](README.md#configure).
5. Crea o registra sin composición de stack obligatoria. Conversa sobre documentos/arquitectura o inventario HEAD;
   revisa/aplica borradores y adopta el perfil propio propuesto. Confirma el commit documental/P001, completa las
   herramientas y guarda el perfil. Confirma preparación acotada (archivos, dependencias, comandos/red), revisa
   el recibo y activa por separado. Solo entonces se habilita la primera tarea. Django/TypeScript son opcionales.
   [Recorrido completo](README.md#start-a-project).

**Edición posterior:** configuración global desde la navegación y perfil desde el proyecto (resumen y Ajustes), por
formulario/TOML. Los formularios guiados cubren agentes y sus capacidades de herramientas, perfiles reutilizables,
composiciones y presets globales y, por proyecto, comandos del perfil (argumentos, directorio, tiempo límite,
entorno, JUnit), prefijos, rutas protegidas/sensibles/de modelo de datos, formateador, rutas instaladas,
autorización/límites y agentes, según lo que permita la etapa del proyecto; los ajustes sin control se conservan en TOML.
La ayuda IA es opcional y usa clientes activos; aplicar una propuesta cambia el borrador. Diff, guardado,
preparación y activación siguen separados. Global se aplica sin reiniciar (salvo lease/poll con el supervisor en
marcha, que la vista previa indica); cambios técnicos de perfil, preparación nueva. Los conflictos conservan el
candidato de la pestaña; recargar no reenvía confirmaciones. Un cambio confirmado espera a los jobs en curso o a un
escritor incierto, que conservan sus ajustes congelados; puedes cancelarlo. [Edición](README.md#edit-configuration-later).

**TOML anteriores:** formatos 1–8 conservan entrada/hashes. Importarlos al editor es explícito; los perfiles
convertidos necesitan documentación comprometida, plan y preparación nuevos antes de activar todo y reiniciar sin
la fuente externa (la promoción de una importación sigue requiriendo reinicio). Esta conversión de configuración es distinta de incorporar un repositorio con código.
Los [ejemplos manuales](examples/local_config.minimal.example.toml) siguen siendo opcionales.

**Contabilidad de uso (opcional):** cada invocación de agente se registra con su evidencia de uso aunque no pueda
valorarse. Para valorarla, convierte explícitamente la configuración global a `local-config-10`, define perfiles de
facturación con nombre (proveedor, plataforma/producto, esquema, unidad, base, paquete de referencias fijado y las
condiciones que declaras) y valores por defecto por rol; cada proyecto puede elegir otro perfil por rol tras pasar a
`project-config-2`. Un perfil se aplica al trabajo admitido tras activarlo, nunca al encolado o pasado, y un cambio
solo de facturación conserva la preparación técnica. **Contabilidad** muestra cobertura, importes por base compatible
y el motivo de cada invocación sin valorar. Son valoraciones locales con precios públicos fijados, no facturas,
saldos ni cuotas, y los precios semilla tienen validez histórica desconocida. El trabajo anterior solo se valora con
los comandos explícitos `accounting-backfill`/`accounting-reprice` ([Operation](README.md#operation)).

Con el supervisor habilitado, cada intento encolado usa tu cuenta/cuota del proveedor. El login de clientes se hace
fuera del harness. El arranque crea solo una DB ausente y nunca migra silenciosamente. Actualizar conserva
las generaciones/datos con `--upgrade --writers-stopped`; la migración de esquema sigue siendo separada.

## Idiomas

Dos ajustes, ambos en inglés o español:

- **Idioma de la interfaz**: global y modificable en cualquier momento desde Preferencias. Rige la interfaz, los
  mensajes del servicio y de la CLI, la conversación con los agentes, sus respuestas y sus preguntas.
- **Idioma de trabajo**: se elige por proyecto al crearlo o incorporarlo (inicializado con el valor global por
  defecto) y después no cambia. Rige la documentación, los planes, las decisiones, el código y los comentarios.

Ejemplo: interfaz en español e idioma de trabajo inglés. Conversas con el revisor en español y lees sus preguntas en
español, mientras que todo lo técnico del proyecto se escribe en inglés, tanto con Codex como con Claude Code. Cada
tarea congela ambos idiomas al encolarse; cambiar después la interfaz solo afecta a las interacciones nuevas.
[Más detalle](README.md#languages).

## Alcance soportado y límites

| Capacidad | Offline (datos sintéticos y agentes falsos) | Con proveedores reales |
|---|---|---|
| Plan → ejecución → validación → revisión → commit, fases, cierre y archivo | Sí | Adaptador actual: tareas Django y TypeScript COMMITTED; fase TypeScript READY, cerrada y archivada |
| Revisor y ejecutor Codex o Claude Code, en las cuatro combinaciones | Sí | Las cuatro antes de `cli-14`; con el actual solo revisor Claude → ejecutor Codex |
| Proyecto Django nuevo con receta | Sí | Creación, cuatro tareas y cierre históricos en macOS ARM64/Python 3.13; creación v2 solo offline |
| Proyecto TypeScript web nuevo con receta | Sí, también con node/npm reales y caché local | v2 e idioma de trabajo español: definición, preparación offline, una tarea COMMITTED y cierre |
| Recetas v2 según el idioma de trabajo | Sí, con herramientas sintéticas | Solo TypeScript v2 en español; sin creación Django v2 real ni matriz completa de idiomas |
| Perfiles declarados e incorporación de repositorios existentes | Sí | Dos Django sintéticos incorporados con originales intactos; clon documental COMMITTED con perfil v8, seis validaciones/13 casos JUnit y formateador nativo (dos archivos sin cambios) |
| Chat, backup y restauración | Sí | Dos respuestas reales, comando determinista sin modelo y propuesta confirmada QUEUED sin ejecutar; consulta API/UI Chrome de runs, diff, JUnit y métricas restaurados |
| Vistas de runs, métricas y vista previa de exportación con historiales grandes | Sí | Vistas/métricas reales restauradas comprobadas; historiales grandes y vista previa de exportación solo sintéticos |
| Contabilidad de uso: captura, valoración con referencias fijadas, agregados, página Contabilidad, backup y consulta restaurada | Sí (calificación P001, streams sintéticos y referencias empaquetadas) | No validada: sin captura real, facturación de cuenta ni comparación con facturas |

Evidencia del adaptador actual: octubre de 2026, macOS ARM64, revisor Claude Code **2.1.310** y ejecutor Codex
**0.164.0**, wheels instalados y proyectos sintéticos desechables. Las cuatro combinaciones y la receta Django
históricas usaron Codex 0.162.1/0.163.0 y Claude Code 2.1.295–2.1.304 antes de `cli-14`. No acredita otras
parejas, versiones, plataformas o proyectos de producción, ni compara modelos o prueba efectos internos de las CLI.
Se mantienen los mínimos y la compatibilidad condicionada. Dos tareas acabaron en REVISION_LIMIT y dos checks
TypeScript fallaron antes de una edición documental autorizada y un READY válido; sus resultados se conservaron.
La propuesta del chat sigue QUEUED y la identidad de procesos históricos sigue siendo incierta.

`local-config-9` añade autoridad global y `project-config-1` por proyecto. Los formatos 1–8 conservan su entrada;
`local-config-8` permite formateador optativo en perfiles declarados y conserva presets/recetas v2; v1–v7 mantienen
sus reglas. La restauración ofrece consulta por id en `/runs/:id` sin proyecto ni checkout, con diff/JUnit/métricas,
sin supervisor ni agentes y con mutaciones rechazadas (409). Consultar no certifica la parada de escritores históricos.
Persisten la contención cooperativa sin aislamiento del sistema operativo, los manifiestos de receta fijos tras
preparar y las validaciones sin hora. Detalle y límites restantes en
[Supported scope and limits](README.md#supported-scope-and-limits) y [STATE](docs/STATE.md).

## Seguridad, operación y contribución

- La contención es cooperativa, no un aislamiento del sistema operativo: registra solo repositorios y herramientas de
  confianza ([Safety model](README.md#safety-model)). Para vulnerabilidades, [SECURITY.md](SECURITY.md).
- Reinicio, actualización con `migrate`, backups, diagnóstico y desinstalación conservando los datos:
  [Operation](README.md#operation).
- Para contribuir: [CONTRIBUTING.md](CONTRIBUTING.md), las instrucciones para agentes en [AGENTS.md](AGENTS.md), el
  [roadmap](docs/ROADMAP.md) y las [decisiones](docs/DECISIONS.md). La documentación técnica, en inglés:
  [especificación](docs/SPECIFICATION.md), [arquitectura](docs/ARCHITECTURE.md),
  [modelo de datos](docs/DDBB-DIAGRAM.md) y [flujos](docs/flows/task-run.md).
