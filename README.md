# TokenAudit

> Observabilidad y contabilidad de tokens para agentes de IA que asisten en el
> desarrollo. Cuánto se gasta, en qué, cuándo y a través de qué sub-agente.

TokenAudit es una colección de skills + hooks que se instalan sobre tu
herramienta de IA (hoy **Claude Code**, más adelante opencode y otros)
para que el equipo entero tenga visibilidad real de su consumo de tokens
y pueda detectar patrones (sesiones largas sin `/clear`, sub-agentes
caros, proyectos que escalan más rápido de lo esperado).

---

## Skills incluidas

### `token-usage`

- Mide el consumo de tokens **por día**, **por proyecto**, **por modelo**
  y **por tipo de sub-agente**.
- Mantiene un `TOKEN_USAGE.md` dentro de cada proyecto con:
  - Totales históricos (lifetime)
  - Desglose diario
  - Últimas 50 sesiones (título auto-detectado, duración, tokens)
  - Historial de consultas append-only (máx. 500)
- Registra un hook `PostToolUse` que, **después de cada delegación a un
  sub-agente**, inyecta automáticamente los tokens que esa delegación
  consumió en la respuesta del agente principal.

---

## Requisitos

- [Claude Code](https://claude.com/claude-code) instalado.
- **Python 3.8+** en el `PATH` (comando `python`, `python3` o `py`).
- **Bash**. En Windows usá **Git Bash** (viene con Git for Windows) o la
  shell de **Laragon**.

---

## Instalación

TokenAudit soporta **dos modos de instalación**. Elegí según cómo lo
quieras usar.

### Modo 1 — **Local (global al usuario)** [recomendado]

Instala la skill y el hook a nivel usuario. Aplica a **todos** los
proyectos que abras con Claude Code en ese ordenador.

```bash
git clone <url-del-repo> TokenAudit
cd TokenAudit
./install.sh
```

Qué toca:

| Ruta | Qué se escribe |
|------|----------------|
| `~/.claude/skills/token-usage/` | Los 3 archivos de la skill |
| `~/.claude/settings.json` | Se **agrega** (merge, no pisa) el hook `PostToolUse` |

Después, **cerrá y volvé a abrir Claude Code** para que cargue el hook.

### Modo 2 — **Por proyecto** (scoped)

Instala la skill y el hook dentro del proyecto donde estés parado.
Aplica **solo a ese proyecto**. Ideal si un proyecto tiene políticas
distintas o si el equipo quiere activar TokenAudit caso por caso.

```bash
# 1) Cloná el repo donde quieras (una sola vez)
git clone <url-del-repo> ~/TokenAudit

# 2) Parate en el proyecto donde lo querés activar
cd /ruta/a/tu/proyecto

# 3) Ejecutá el install apuntando al script del repo clonado
~/TokenAudit/install.sh --project
```

Qué toca (relativo al proyecto actual):

| Ruta | Qué se escribe |
|------|----------------|
| `<tu-proyecto>/.claude/skills/token-usage/` | Los 3 archivos de la skill |
| `<tu-proyecto>/.claude/settings.json` | Se agrega el hook `PostToolUse` |

El hook usa `${CLAUDE_PROJECT_DIR}` para resolver la ruta, así que si
movés el proyecto de carpeta, sigue funcionando sin reinstalar.

**Decisión importante sobre `.claude/` en el proyecto:**

- Si querés que **todo el equipo** que clone ese proyecto use
  TokenAudit automáticamente → **commiteá** la carpeta `.claude/`.
- Si es solo para vos → **agregá `.claude/` al `.gitignore`** del
  proyecto.

### ¿Cuál modo uso?

| Caso | Modo |
|------|------|
| Tu ordenador personal, querés medir todo lo que hacés | **Local** |
| Equipo grande, algunos proyectos sí, otros no | **Proyecto** |
| Querés que todo el equipo tenga TokenAudit al clonar un repo específico | **Proyecto** (y commiteá `.claude/`) |
| No estás seguro | **Local** — es el default y el más simple |

### Idempotencia

Los scripts son idempotentes: correrlos dos veces no duplica nada. Si ya
existía el hook, lo **actualiza** en lugar de agregar uno nuevo.

---

## Uso

Dentro de Claude Code:

| Comando | Qué hace |
|---------|----------|
| `/token-usage` | Tokens de hoy, actualiza `TOKEN_USAGE.md` del proyecto |
| `/token-usage yesterday` | Ayer |
| `/token-usage week` | Últimos 7 días |
| `/token-usage month` | Últimos 30 días |
| `/token-usage all` | Todo el historial disponible |
| `/token-usage week --export` | Semana + snapshot JSON en `~/.claude/token-usage/` |
| `/token-usage month --project <substr>` | Filtrar por nombre de proyecto |
| `/token-usage today --no-registry` | No tocar `TOKEN_USAGE.md` en esta corrida |

Cuando el agente principal delega a un sub-agente, vas a ver
automáticamente una línea así abajo del resultado:

```
[token-usage] Sub-agente `claude-code-guide` — Verificar hook schema
  total_tokens=15910 | tool_uses=2 | duration_ms=27482
```

Esa línea la inyecta el hook — vos no tenés que hacer nada.

---

## Qué es el `TOKEN_USAGE.md` en cada proyecto

La primera vez que corrés `/token-usage` en un proyecto, se genera un
`TOKEN_USAGE.md` en la raíz del proyecto. Ese archivo es el registro
persistente: vive en el proyecto, crece con el tiempo y tiene:

- **Totales históricos**: facturado total, input/output/caché, mensajes,
  cantidad de sesiones.
- **Desglose diario**: tabla por fecha × modelo × agente.
- **Sesiones**: las últimas 50 con título auto-detectado, duración,
  tokens y un contador de reinicios de contexto.
- **Historial de consultas**: append-only, una línea por cada vez que
  alguien corrió `/token-usage` en ese proyecto.

> **Recomendación fuerte:** agregá `TOKEN_USAGE.md` a tu `.gitignore`
> (o al `~/.config/git/ignore` global) si no querés que quede
> commiteado. Es un archivo personal/del equipo, no forma parte del
> código.

---

## Actualizar TokenAudit

```bash
cd ~/TokenAudit
git pull
./install.sh              # o --project si esa fue tu instalación
```

Después, reiniciá Claude Code.

---

## Desinstalar

```bash
./uninstall.sh            # modo local
./uninstall.sh --project  # modo proyecto (parate en el proyecto primero)
```

Borra la carpeta de la skill (`~/.claude/skills/token-usage/` o
`<proyecto>/.claude/skills/token-usage/`) y quita la entrada del hook
del `settings.json` correspondiente. Respeta cualquier otro hook que
hubiera ahí.

Los `TOKEN_USAGE.md` ya generados en tus proyectos **quedan intactos**:
son tu historial. Si los querés borrar, hacelo a mano.

---

## Roadmap / cómo mapea al futuro

Hoy TokenAudit funciona con **Claude Code**. La estructura del repo
está pensada para escalar a otras herramientas sin romper nada:

```
TokenAudit/
├── skills/
│   └── token-usage/          ← la skill actual (formato Claude Code)
│
├── adapters/                 ← [futuro] adaptadores por herramienta
│   ├── opencode/
│   ├── cursor/
│   └── aider/
│
├── install.sh
├── uninstall.sh
└── README.md
```

Cuando venga el soporte para opencode u otros agentes, se agregará el
adaptador correspondiente dentro de `adapters/` y el `install.sh`
detectará automáticamente qué herramientas tenés instaladas y aplicará
los artefactos correctos. Los datos (transcripts, sesiones, tokens) de
cada herramienta van a un sub-archivo del `TOKEN_USAGE.md` del
proyecto, así tenés una vista unificada.

Si querés contribuir un adaptador, abrí un issue con el formato de
transcripts de la herramienta y armamos juntos el esqueleto.

---

## Problemas comunes

**El hook no aparece después de delegar a un sub-agente**
Reiniciá Claude Code. Los hooks se cargan al iniciar la sesión — no
basta con reejecutar el `install.sh`.

**`python: command not found` al correr `install.sh`**
Python 3.8+ no está en el `PATH`. En Windows, instalalo desde
<https://www.python.org/downloads/> marcando **"Add Python to PATH"**.
Cerrá y reabrí la terminal antes de probar de nuevo.

**Las tildes se ven como `?` o caracteres raros en consola**
El script ya reconfigura `stdout` a UTF-8. Si aún falla, en la misma
terminal probá `chcp 65001` antes de correr Claude Code.

**El `install.sh` tira `$'\r': command not found`**
Se grabó con line endings CRLF (típico de Windows). En el repo hay un
`.gitattributes` que fuerza LF, pero si por alguna razón no se aplicó,
convertilo:

```bash
sed -i 's/\r$//' install.sh uninstall.sh
```

**Quiero ver qué payload recibe el hook para debuguear**
Editá `~/.claude/skills/token-usage/subagent_tokens_hook.py` (o la copia
del proyecto si instalaste en modo `--project`) y agregá al principio
de `main()`:

```python
import sys
print("DEBUG payload:", sys.stdin.read()[:2000], file=sys.stderr)
```

Los mensajes a stderr aparecen en el transcript de Claude Code.

---

## Licencia

MIT — usá, forkea, modificá. Si mejorás algo, mandá PR.
