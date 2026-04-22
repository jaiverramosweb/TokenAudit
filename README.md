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

- **Lee dos fuentes en paralelo** y las combina:
  - **Claude Code** — JSONL en `~/.claude/projects/*/*.jsonl`
  - **opencode** — SQLite en `~/.local/share/opencode/opencode.db`
- Si solo tenés una de las dos herramientas instaladas, la otra se omite
  silenciosamente.
- Mide el consumo de tokens **por día**, **por proyecto**, **por modelo**
  y **por tipo de sub-agente**. Incluye **costo USD** cuando el
  proveedor de opencode lo reporta.
- Mantiene un `TOKEN_USAGE.md` dentro de cada proyecto (agrupado por el
  `cwd` real — un mismo proyecto con datos de Claude Code **y** opencode
  se unifica en un único `.md`) con:
  - Totales históricos (lifetime) de ambas fuentes combinadas
  - Desglose diario con columna `Src` (`CC`/`OC`) y `Costo USD`
  - Últimas 50 sesiones (título auto-detectado, duración, tokens, costo).
    Sub-agentes de opencode (`session.parent_id` distinto de null)
    aparecen marcados con `↳`.
  - Historial de consultas append-only (máx. 500)
- Registra un hook `PostToolUse` en Claude Code que, **después de cada
  delegación a un sub-agente**, inyecta automáticamente los tokens que
  esa delegación consumió en la respuesta del agente principal.
  *(opencode tiene su propio modelo de sub-agentes — se captura por
  lectura del DB, no necesita hook.)*

---

## Requisitos

- [Claude Code](https://claude.com/claude-code) instalado.
- **Python 3.8+** en el `PATH` (comando `python`, `python3` o `py`).
- **Bash**. En Windows usá **Git Bash** (viene con Git for Windows) o la
  shell de **Laragon**.

---

## Instalación

Dos **modos** posibles:

- **Local** (global al usuario, en `~/.claude/`) — aplica a **todos** tus
  proyectos. Es el recomendado para uso personal.
- **Por proyecto** (scoped, en `./.claude/`) — aplica solo al proyecto
  donde estés parado.

Y dos **formas** de ejecutar el install (elegí la que prefieras):

### Forma A — Una sola línea con `curl` [la más simple]

Si confiás en correr scripts remotos (ver [aviso de seguridad](#seguridad-curl--bash)):

**Modo local:**

```bash
curl -fsSL https://raw.githubusercontent.com/<TU-USUARIO>/TokenAudit/main/bootstrap.sh | bash
```

**Modo proyecto** (parate primero en el proyecto):

```bash
cd /ruta/a/tu/proyecto
curl -fsSL https://raw.githubusercontent.com/<TU-USUARIO>/TokenAudit/main/bootstrap.sh | bash -s -- --project
```

El `bootstrap.sh`:

1. Clona el repo a `~/TokenAudit/` (si ya existe, hace `git pull --ff-only`).
2. Ejecuta `install.sh` pasándole los argumentos que le diste (ej `--project`).

**Overrides útiles** (variables de entorno antes del `bash`):

| Variable | Default | Qué hace |
|----------|---------|----------|
| `TOKENAUDIT_REPO` | la del `bootstrap.sh` | Usar otro repo (útil para forks) |
| `TOKENAUDIT_BRANCH` | `main` | Usar otra rama |
| `TOKENAUDIT_DIR` | `~/TokenAudit` | Clonar en otra carpeta |

Ejemplo:

```bash
TOKENAUDIT_BRANCH=dev curl -fsSL https://.../bootstrap.sh | bash
```

### Forma B — Clone manual [la transparente]

Si preferís ver todo lo que estás instalando antes de ejecutarlo:

```bash
git clone https://github.com/<TU-USUARIO>/TokenAudit.git ~/TokenAudit
cd ~/TokenAudit
./install.sh               # modo local
# o
./install.sh --project     # modo proyecto (parate primero en el proyecto)
```

### Qué toca cada modo

**Modo local:**

| Ruta | Qué se escribe |
|------|----------------|
| `~/.claude/skills/token-usage/` | Los 3 archivos de la skill |
| `~/.claude/settings.json` | Se **agrega** (merge, no pisa) el hook `PostToolUse` |

**Modo proyecto** (relativo al proyecto actual):

| Ruta | Qué se escribe |
|------|----------------|
| `<tu-proyecto>/.claude/skills/token-usage/` | Los 3 archivos de la skill |
| `<tu-proyecto>/.claude/settings.json` | Se agrega el hook `PostToolUse` |

El hook en modo proyecto usa `${CLAUDE_PROJECT_DIR}` para resolver la
ruta, así que si movés el proyecto de carpeta, sigue funcionando sin
reinstalar.

**Decisión importante sobre `.claude/` en un proyecto:**

- Si querés que **todo el equipo** que clone ese proyecto use
  TokenAudit automáticamente → **commiteá** la carpeta `.claude/`.
- Si es solo para vos → **agregá `.claude/` al `.gitignore`** del
  proyecto.

### Después de instalar

**Cerrá y volvé a abrir Claude Code** para que cargue el hook nuevo
(los hooks se leen al iniciar la sesión, no en caliente).

### ¿Qué modo uso?

| Caso | Modo |
|------|------|
| Tu ordenador personal, querés medir todo | **Local** |
| Equipo grande, algunos proyectos sí otros no | **Proyecto** |
| Querés que todo el equipo tenga TokenAudit al clonar el repo de un proyecto | **Proyecto** + commitear `.claude/` |
| No estás seguro | **Local** — es el default y el más simple |

### Idempotencia

Tanto `install.sh` como `bootstrap.sh` son **idempotentes**: correrlos
dos veces no duplica nada. Si ya existía el hook, lo **actualiza** en
lugar de agregar uno nuevo.

### Seguridad (`curl | bash`)

Ejecutar un script remoto directamente vía `curl | bash` significa
correr código sin haberlo leído. Para equipos internos con acceso al
repo, la confianza ya existe. Si publicás TokenAudit afuera, recomendá
esta variante a los paranoicos:

```bash
curl -fsSL https://raw.githubusercontent.com/<TU-USUARIO>/TokenAudit/main/bootstrap.sh -o bootstrap.sh
less bootstrap.sh     # revisá el contenido
bash bootstrap.sh     # ahora sí
```

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

**Con el one-liner** (equivalente a reinstalar — el `bootstrap.sh` hace
`git pull --ff-only` si el repo ya existe):

```bash
curl -fsSL https://raw.githubusercontent.com/<TU-USUARIO>/TokenAudit/main/bootstrap.sh | bash
```

**Manualmente:**

```bash
cd ~/TokenAudit
git pull
./install.sh              # o --project si esa fue tu instalación
```

Después de cualquier update, **reiniciá Claude Code** para que tome los
cambios del hook.

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

Hoy TokenAudit funciona con **Claude Code** y **opencode**. La
estructura del repo está pensada para escalar a otras herramientas sin
romper nada:

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

**Estado actual:** la skill `token-usage` ya lee Claude Code + opencode
en un solo pase y los unifica en un único `TOKEN_USAGE.md` por proyecto.
La carpeta `adapters/` existe en el roadmap para albergar futuros
adaptadores (cursor, aider, etc.) cuando el esfuerzo lo justifique.

**Próximos candidatos:**

- **Cursor CLI / aider** — si exponen transcripts locales, es el mismo
  patrón que opencode: un módulo nuevo `collect_records_<tool>` que
  traduce al formato interno unificado.
- **Pricing por modelo** — para computar costo USD de Claude Code (hoy
  opencode reporta el costo nativo cuando el provider lo expone; Claude
  Code no lo reporta, así que queda en `$0` hasta que sumemos una tabla
  de precios por modelo).

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

---

## Setup inicial (solo para el que publica el repo)

Si sos quien va a publicar TokenAudit por primera vez en GitHub/GitLab:

1. **Creá el repo vacío** en tu org (sin README auto-generado).

2. **Editá `bootstrap.sh`** y reemplazá el placeholder:

   ```bash
   # antes
   DEFAULT_REPO="https://github.com/CHANGEME/TokenAudit.git"
   # después
   DEFAULT_REPO="https://github.com/tu-usuario/TokenAudit.git"
   ```

3. **Editá este README** y reemplazá todas las ocurrencias de
   `<TU-USUARIO>` por tu usuario/org real (hay varias en las secciones
   de instalación y actualización).

4. **Primer push:**

   ```bash
   cd ~/TokenAudit
   git add .
   git commit -m "feat: TokenAudit v2 con soporte Claude Code + opencode"
   git branch -M main
   git remote add origin https://github.com/tu-usuario/TokenAudit.git
   git push -u origin main
   ```

5. **Probá el one-liner vos mismo** antes de compartirlo con el equipo:

   ```bash
   # Borrá tu instalación local primero para simular fresh install
   rm -rf ~/TokenAudit
   curl -fsSL https://raw.githubusercontent.com/tu-usuario/TokenAudit/main/bootstrap.sh | bash
   ```

6. **Compartí al equipo** con la línea documentada arriba — los mismos
   overrides (`TOKENAUDIT_BRANCH`, etc.) les sirven si necesitan tunear
   algo.

> **Si el repo es privado**, el `curl` necesita auth. Las opciones son:
> (a) hacer el repo público, (b) usar `gh repo clone` + correr
> `install.sh` manualmente, o (c) que el equipo configure credenciales
> git antes del `curl`.
