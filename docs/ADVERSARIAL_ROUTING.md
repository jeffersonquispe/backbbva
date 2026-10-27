# Tres salidas del primer adversarial

`detector_adversarial` revisa todas las conclusiones del Detector, incluidas
`not_fraud`. Su salida incorpora `decision`, con tres valores de dominio:

| Decisión | Comportamiento | Resultado operativo |
| --- | --- | --- |
| `pass` | Omite Clasificación, segundo Adversarial y Analista agente; ejecuta Ejecutor y Post-proceso | Alerta `CLOSED`, sin acción externa |
| `scale_to_analyst` | Omite esos mismos pasos; Ejecutor envía a la cola humana | Workflow `SUCCEEDED`, alerta `ESCALATED`; espera incluso sin capacidad inmediata |
| `handle_by_aria` | Continúa con Clasificación, segundo Adversarial y Analista agente | Resolución habitual según evidencia y playbook |

El Detector aporta evidencia; su `is_fraud` no sustituye la decisión del primer
adversarial. Datos ausentes no justifican `pass`. La incertidumbre que no se
puede resolver con las herramientas corresponde a `scale_to_analyst`.

`requires_classification_feedback` se conserva para correcciones internas de
contradicciones concretas del Detector. Mientras sea verdadero, se repite el
Detector dentro del límite configurado y no se aplica `decision`. La revisión
final usa el mismo número de intento que el Detector corregido. Al agotar el
límite, sigue vigente la escalada por fallo, sin reintento automático de Celery.
El segundo adversarial mantiene su contrato de feedback al Clasificador.

## Superficies afectadas

- **LLM y DTO:** el primer revisor exige una decisión válida además del booleano
  `has_issues`. Una respuesta incompleta, un valor desconocido o un booleano
  serializado como texto no certifican la alerta. Los prompts completos de
  prueba para `detector_adversarial` deben incluir `decision`; los del segundo
  revisor conservan su formato. Los prompts adicionales del segmento reciben
  el protocolo nuevo automáticamente.
- **Workflow y ejecución:** desaparece el cierre anticipado del Detector. Las
  dos rutas terminales conservan Ejecutor y Post-proceso, persistencia, estado
  de la operación y métricas. Escalar por incertidumbre no activa el fallback
  de bloqueo por falta de analistas. No cambia el playbook de las resoluciones
  que decide el Analista agente.
- **Pruebas de datasets y replay del optimizador:** no ejecutan acciones
  operativas ni reservan recursos; registran `simulated` y `proposed_action`.
  Las métricas de pruebas incluyen `pass` como `not_fraud` y escalada como
  `unknown`. El optimizador cuenta la escalada como sin decisión y no toma
  como predicción el veredicto anterior del Detector. Registros antiguos sin
  `decision` conservan la lectura anterior.
- **Frontend:** el recorrido muestra Detector y ambos revisores; muestra las
  tres salidas del primero y el resultado simulado. El diagrama de una alerta
  puede obtener su resolución del primer revisor si no hubo Analista agente.
- **E07:** acepta la escalada directa sin exigir pasos omitidos por diseño.
  No cambia ninguna ruta HTTP, tabla ni firma de tarea Celery.

## Verificación

La cobertura incluye las nueve combinaciones de veredicto del Detector y
salida del primer revisor, corrección y numeración de intentos, límite cero,
respuestas inválidas, escalada sin capacidad, aislamiento de test/replay y
lectura de decisiones en métricas y optimizador.

`frontend_mockup/e2e/adversarial-routing-real.spec.ts` ejercita las tres salidas
por nginx en `http://localhost`, con dataset, API, LLM y Celery reales. Usa los
overrides de prompt admitidos por las pruebas y una configuración inactiva;
verifica persistencia, pasos ejecutados/omitidos, simulación y texto en UI.
No intercepta peticiones API ni sustituye servicios. Es una prueba de
contrato y enrutamiento, no una evaluación de calidad del criterio del LLM.

Ejecución focalizada desde backend:

```sh
make e2e-selected-real E2E_TEST_FILES=e2e/adversarial-routing-real.spec.ts
```

La regresión general requiere además `make e2e-all-local` y
`make e2e-observability` conforme a `AGENTS.md`.

## Contexto de los agentes

El grafo del proyecto y el prompt del especialista de configuración explican
las tres salidas y su interpretación en el replay del optimizador. El asistente
recibe el grafo como contexto de sus consultas. Los prompts versionados de
entornos existentes deben actualizarse mediante una nueva versión; las
sesiones anteriores conservan sus pins. El seguimiento está en
`PENDIENTES_MVC.md`.

Durante la regresión general también se corrigieron dos problemas de soporte:
la prueba del drawer del optimizador libera sus propias sesiones sintéticas
antes de comprobar la disponibilidad del formulario, y el repositorio de
esquemas recorre todas las páginas de DynamoDB para encontrar la versión
activa y asignar nuevas versiones. El catálogo local había superado una página;
la omisión bloqueaba la preparación del E2E con un falso conflicto de versión.
