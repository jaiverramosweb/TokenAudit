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
- **Para la instalación**: una de las dos opciones:
  - **PowerShell 5.1+** (viene con Windows — sirve sin instalar nada más), o
  - **Bash**: Git Bash en Windows (viene con [Git for Windows](https://git-scm.com/download/win)),
    Laragon shell, o bash nativo en macOS/Linux.

> **Importante en Windows**: los comandos `curl | bash` **no funcionan
> en CMD ni en PowerShell** (distinta sintaxis, problemas de curl
> nativo con schannel en redes corporativas). Usá alguna de estas tres:
>
> 1. **PowerShell + `iwr | iex`** — instalador PowerShell nativo, no
>    requiere Git for Windows. Ver sección "PowerShell" abajo.
> 2. **Git Bash + `curl | bash`** — si ya lo tenés abierto. Buscá
>    "Git Bash" en el menú inicio.
> 3. **Clone manual** — `git clone` + `./install.sh`. Requiere Git.

---

## Instalación

Dos **modos** posibles:

- **Local** (global al usuario, en `~/.claude/`) — aplica a **todos** tus
  proyectos. Es el recomendado para uso personal.
- **Por proyecto** (scoped, en `./.claude/`) — aplica solo al proyecto
  donde estés parado.

Y dos **formas** de ejecutar el install (elegí la que prefieras):

### Forma A — Una sola línea [la más simple]

Si confiás en correr scripts remotos (ver [aviso de seguridad](#seguridad-curl--bash)). Elegí según tu shell:

#### Git Bash (Windows), macOS, Linux

**Modo local:**

```bash
curl -fsSL https://raw.githubusercontent.com/jaiverramosweb/TokenAudit/main/bootstrap.sh | bash
```

**Modo proyecto** (parate primero en el proyecto):

```bash
cd /ruta/a/tu/proyecto
curl -fsSL https://raw.githubusercontent.com/jaiverramosweb/TokenAudit/main/bootstrap.sh | bash -s -- --project
```

#### PowerShell (Windows) — sin Git for Windows requerido

Solo necesita **Python 3.8+**. Opcionalmente detecta Git for Windows y
lo usa (más rápido); si no, cae automáticamente a un camino PowerShell
nativo que descarga el repo como ZIP.

**Modo local:**

```powershell
iwr -useb https://raw.githubusercontent.com/jaiverramosweb/TokenAudit/main/bootstrap.ps1 | iex
```

**Modo proyecto** (PowerShell no acepta args vía `| iex`; hay dos
formas):

Opción A — con env var (una sola línea):

```powershell
$env:TOKENAUDIT_PROJECT=1
iwr -useb https://raw.githubusercontent.com/jaiverramosweb/TokenAudit/main/bootstrap.ps1 | iex
Remove-Item Env:TOKENAUDIT_PROJECT
```

Opción B — descargar + ejecutar (para pasar otros flags):

```powershell
cd C:\ruta\a\tu\proyecto
$tmp = "$env:TEMP\tokenaudit-bootstrap.ps1"
iwr -useb https://raw.githubusercontent.com/jaiverramosweb/TokenAudit/main/bootstrap.ps1 -OutFile $tmp
& $tmp --project
Remove-Item $tmp
```

> **Forzar el camino PowerShell nativo** (sin usar Git Bash aunque esté
> instalado): `$env:TOKENAUDIT_NO_BASH=1` antes del `iex`. Útil para
> debuggear o para usuarios que NO tienen Git for Windows instalado —
> el script descarga el repo como ZIP desde GitHub, no necesita `git`.

#### ¿Cómo funciona?

El `bootstrap.sh` (o `bootstrap.ps1`, que lo invoca vía `bash.exe`):

1. Clona el repo a `~/TokenAudit/` (si ya existe, hace `git pull --ff-only`).
2. Ejecuta `install.sh` pasándole los argumentos que le diste (ej `--project`).

**Overrides útiles** (variables de entorno antes del comando):

| Variable | Default | Qué hace |
|----------|---------|----------|
| `TOKENAUDIT_REPO` | la hardcodeada | Usar otro repo (útil para forks) |
| `TOKENAUDIT_BRANCH` | `main` | Usar otra rama |
| `TOKENAUDIT_DIR` | `~/TokenAudit` | Clonar/extraer en otra carpeta |
| `TOKENAUDIT_PROJECT` | `0` | `=1` → modo proyecto sin flag (útil con `iex`) |
| `TOKENAUDIT_NO_BASH` | `0` | `=1` → saltear camino bash en PowerShell, usar solo ZIP |

Ejemplo (Git Bash):

```bash
TOKENAUDIT_BRANCH=dev curl -fsSL https://.../bootstrap.sh | bash
```

Ejemplo (PowerShell):

```powershell
$env:TOKENAUDIT_BRANCH="dev"
iwr -useb https://.../bootstrap.ps1 | iex
```

### Forma B — Clone manual [la transparente]

Si preferís ver todo lo que estás instalando antes de ejecutarlo:

```bash
git clone https://github.com/jaiverramosweb/TokenAudit.git ~/TokenAudit
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

### Seguridad (`curl | bash` y `iwr | iex`)

Ejecutar un script remoto directamente vía `curl | bash` o `iwr | iex`
significa correr código sin haberlo leído. Para equipos internos con
acceso al repo, la confianza ya existe. Para los paranoicos:

**Git Bash / macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/jaiverramosweb/TokenAudit/main/bootstrap.sh -o bootstrap.sh
less bootstrap.sh     # revisá el contenido
bash bootstrap.sh     # ahora sí
```

**PowerShell:**

```powershell
iwr -useb https://raw.githubusercontent.com/jaiverramosweb/TokenAudit/main/bootstrap.ps1 -OutFile bootstrap.ps1
notepad bootstrap.ps1    # revisá el contenido
.\bootstrap.ps1          # ahora sí
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

Volvé a correr **la misma línea** con la que instalaste. El bootstrap es
idempotente: si el clone ya existe hace `git pull --ff-only` y reinstala.

**Git Bash / macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/jaiverramosweb/TokenAudit/main/bootstrap.sh | bash
```

**PowerShell:**

```powershell
iwr -useb https://raw.githubusercontent.com/jaiverramosweb/TokenAudit/main/bootstrap.ps1 | iex
```

**Manualmente (si clonaste con Forma B):**

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

**`curl: (35) schannel: CRYPT_E_NO_REVOCATION_CHECK`** (típico en redes
corporativas con proxy/firewall). Pasa cuando tu Git Bash termina usando
el `curl.exe` nativo de Windows (en `System32`) en vez del de Git for
Windows (`/mingw64/bin/curl`). El de Windows usa `schannel` y no puede
chequear la revocación del cert cuando hay interceptación TLS de por
medio. Verificalo con `which curl`. Hay tres salidas, en orden de
preferencia:

1. **Usar `git clone` en vez de `curl`** (lo más robusto, git ya sabe
   atravesar el proxy corporativo si podés clonar cualquier otro repo):
   ```bash
   git clone https://github.com/jaiverramosweb/TokenAudit.git ~/TokenAudit && ~/TokenAudit/install.sh
   ```
   Para modo proyecto, agregá `--project` al final.

2. **Forzar el curl bueno de Git Bash** (el de OpenSSL, no schannel):
   ```bash
   /mingw64/bin/curl -fsSL https://raw.githubusercontent.com/jaiverramosweb/TokenAudit/main/bootstrap.sh | bash
   ```

3. **Pedirle al curl de Windows que no chequee revocación** (funciona
   pero deja un flag de seguridad bajado):
   ```bash
   curl --ssl-no-revoke -fsSL https://raw.githubusercontent.com/jaiverramosweb/TokenAudit/main/bootstrap.sh | bash
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

## Forkear TokenAudit (para tu propio repo)

Si querés mantener tu propia variante:

1. Forkeá o cloneá el repo.
2. Editá `bootstrap.sh`: cambiá `DEFAULT_REPO` por la URL de tu fork.
3. Editá este README: reemplazá `jaiverramosweb` por tu usuario.
4. Commit + push a tu fork.

Si tu fork es **privado**, el `curl | bash` requiere auth. Alternativas:
(a) hacer el repo público, (b) `gh repo clone` + `./install.sh`
manualmente, o (c) configurar credenciales git antes del `curl`.
