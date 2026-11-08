# NuclearWatch AI

App móvil (Android primero) que muestra, por región, señales públicas y verificables
relacionadas con riesgo nuclear. **No es un sistema oficial de alerta** y nunca muestra
probabilidades: solo niveles explicados (Normal, Atención, Elevado, Alto), su confianza
y los comunicados oficiales tal cual se publicaron.

## Cómo funciona

```
Fuentes públicas ──► pipeline Python (GitHub Actions, cada hora) ──► JSON en GitHub Pages ──► app Flutter
                                              └──► Firebase (avisos push, apagados en calibración)
```

| Fuente | Qué aporta | Capa |
| --- | --- | --- |
| OIEA (RSS) | comunicados oficiales | Alerta oficial (no altera el nivel) |
| Safecast (CC0) | radiación medida por ciudadanos | Señal radiológica |
| EPA RadNet | monitores oficiales de EE. UU. | Señal radiológica |
| GDELT DOC 2.0 | volumen de noticias nucleares | Señal mediática (techo: nivel 1) |

Reglas completas: `config/rules.yaml` y `docs/metodo.md`.

## Estructura

```
config/     regiones, fuentes, reglas versionadas, contexto estructural
pipeline/   código Python (fuentes → señales → niveles → avisos → publicación)
  tests/    27 pruebas con datos simulados, sin internet
docs/       método y decisiones
.github/workflows/   pipeline horario y pruebas
app/        (paso 2) aplicación Flutter
```

## Puesta en marcha (una sola vez)

1. Crear una cuenta gratuita en GitHub y un repositorio **público** llamado `nuclearwatch`
   (los repositorios públicos tienen Actions y Pages sin costo).
2. Subir esta carpeta al repositorio.
3. En el repositorio: **Actions** → "Pipeline de datos" → **Run workflow**. La primera
   ejecución crea la rama `gh-pages` con los datos.
4. **Settings → Pages**: origen "Deploy from a branch", rama `gh-pages`, carpeta `/ (root)`.
   Los datos quedan en `https://<usuario>.github.io/nuclearwatch/latest.json`.

Desde ahí corre solo cada hora. Las notificaciones siguen apagadas
(`notifications.enabled: false`) hasta terminar los 30 días de calibración.

## Probar en el PC

```
cd pipeline
pip install -r requirements.txt
python -m pytest -q tests
python run.py --site ../site      # ejecución real contra las fuentes
```
