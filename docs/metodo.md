# Método de evaluación (reglas v2026.11-1)

## Tres capas que nunca se mezclan

1. **Alerta oficial**: comunicado del OIEA que menciona la región y contiene palabras de
   incidente. Se muestra 7 días con enlace al original. No cambia el nivel.
2. **Señales medidas**: radiológica y mediática.
3. **Confianza**: cuántas fuentes independientes tienen datos de menos de 6 horas.

## Señal radiológica

Cada estación se compara con su propia mediana de 30 días usando z robusto
(mediana y MAD). Una lectura es alta si z ≥ 4 en **2 lecturas seguidas**.
Se exigen 72 lecturas de línea base; antes de eso la estación está "aprendiendo".
Estaciones sin datos en 6 horas no cuentan.

- 1 estación anómala → nivel 1 (Atención)
- 2 o más → señal radiológica activa → nivel 2 (Elevado)

## Señal mediática

Artículos/día de GDELT con términos nucleares y geográficos de la región, frente a su
mediana de 90 días. Activa si dos días completos seguidos superan 3 veces la mediana
y al menos 20 artículos. **Sola nunca pasa de nivel 1.**

## Niveles

| Nivel | Condición |
| --- | --- |
| 0 Normal | sin señales |
| 1 Atención | señal mediática, o una sola estación anómala |
| 2 Elevado | señal radiológica (2+ estaciones) |
| 3 Alto | radiológica + mediática, con confianza media o alta |

## Notificaciones

Solo niveles 2-3 sostenidos en 2 ejecuciones, máximo 1 cada 12 h por región;
bajadas se avisan tras 24 h sostenidas; comunicados oficiales de incidente siempre.
Si más de 3 regiones suben a la vez no se envía nada y se abre un aviso para revisión.
Durante los primeros 30 días las notificaciones solo se registran (`state/outbox.json`).

## Limitaciones conocidas

- Safecast tiene cobertura desigual y su línea base tarda ~3 días en formarse por estación.
- RadNet solo cubre EE. UU.; EURDEP no permite descarga pública.
- La lluvia eleva la radiación natural (radón): umbrales provisionales hasta calibrar.
- El volumen de noticias refleja atención mediática, no riesgo medido.
- Formatos de Safecast, GDELT y OIEA se validan en la primera ejecución real
  (`latest.json` → `sources`); RadNet ya fue verificado.
