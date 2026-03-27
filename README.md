# sw-git-workspace-global-viewer

Visor global y de solo lectura para revisar el estado de multiples repositorios Git en un workspace.

## Incluye

- Agente reusable: `.github/agents/git-workspace-global-viewer.agent.md`
- Script escaner: `scripts/git-global-viewer.py`
- Dashboard generado: `dashboard/global-git-dashboard.md`

## Uso rapido

```powershell
python scripts/git-global-viewer.py --root "C:/Users/artur/development" --max-depth 3 --output dashboard/global-git-dashboard.md
```

## Garantias del script

- No ejecuta comandos mutantes (`add`, `commit`, `push`, `pull`, `checkout`)
- Solo usa lectura: `git branch`, `git rev-parse`, `git rev-list`, `git status`, `git log`
- Ignora carpetas pesadas: `node_modules`, `vendor`, `.venv`, `dist`, `build`

## Salida

Tabla Markdown con:

- Repositorio
- Rama actual
- Sync remoto (ahead/behind/up to date)
- Cambios locales (modificados/anadidos/eliminados/untracked)
- Ultimo commit

Y una seccion de alertas para:

- `Detached HEAD`
- Repos con cambios locales
- Repos potencialmente desactualizados (sin commits recientes)
