# career-agent

Asistente con generación aumentada por recuperación (RAG) que responde preguntas sobre mi perfil profesional usando solo los archivos Markdown de `data/`. Usa la API de Gemini para el chat y los embeddings, guarda los vectores en MongoDB Atlas Vector Search y combina un ranking léxico con uno semántico mediante Reciprocal Rank Fusion; luego un grafo de LangGraph aplica Corrective RAG: evalúa si la evidencia contiene el dato pedido, reformula la consulta y vuelve a buscar una vez si no alcanza, y solo entonces genera una respuesta basada en la evidencia. Instala el proyecto con `pip install -r requirements.txt -e .`, define `GOOGLE_API_KEY` y las variables de MongoDB en `.env`, indexa los documentos con `python -m career_agent.cli --index`, haz una consulta con `python -m career_agent.cli "¿Qué proyectos usan MongoDB?"`; para levantar el API HTTP (`POST /ask`) usa `uvicorn career_agent.api:app` o el `Dockerfile`, para explorar el grafo usa `langgraph dev`, para correr las pruebas usa `python -m unittest discover -s test` y para medir el retrieval (Hit@1 y MRR sobre `evals/retrieval_questions.json`) usa `python -m career_agent.evals` para medir las respuestas finales (`evals/answer_questions.json`) usa `python -m career_agent.evals --answers` y para medir los seguimientos de conversación usa `--followups`; agrega `--full-context` a cualquiera de los dos para comparar contra la alternativa sin búsqueda.

```mermaid
flowchart LR
    Q[Pregunta] --> R[retrieve: búsqueda híbrida RRF top 5]
    D[(data/*.md)] --> R
    V[(Atlas Vector Search)] --> R
    R --> G{grade_evidence}
    G -->|suficiente| GEN[generate]
    G -->|insuficiente, máximo 1 vez| W[rewrite_query]
    W --> R
    GEN --> A[Respuesta]
```

## RAG contra contexto completo

Todo el perfil suma unos 3.450 tokens, así que cabe completo en el contexto de Gemini y la búsqueda podría parecer innecesaria. Lo medí con los mismos evals, el mismo prompt y el mismo modelo, cambiando solo cómo se obtiene la evidencia:

| Métrica | RAG + Corrective RAG | Contexto completo |
|---|---|---|
| Respuestas correctas (15 preguntas) | 15/15 | 15/15 |
| Seguimientos que aportan datos nuevos | 9/9 en 3 corridas | 3/6 en 2 corridas |
| Latencia promedio en la misma ventana | 15,4 s | 5,9 s |
| Llamadas al modelo por pregunta | 2 a 4 | 1 |
| Infraestructura | MongoDB Atlas y embeddings | Ninguna |

En preguntas directas empatan y el contexto completo es más rápido y barato; en conversaciones de varios turnos gana el RAG, porque la búsqueda acota el tema y el modelo profundiza en lugar de saltar a otra parte del perfil. Mantengo el RAG por esa ventaja y porque escala si el corpus crece; el modo de contexto completo queda disponible para repetir la comparación. Las latencias se midieron en el tier gratuito de Gemini y varían entre corridas.

## Tecnologías

| Área | Tecnología | Uso |
|---|---|---|
| Lenguaje | Python 3.12 | Todo el proyecto |
| Modelos | Gemini `gemini-3.5-flash-lite` | Generación de respuestas |
| Modelos | Gemini `gemini-embedding-2` (768 dimensiones) | Embeddings de documentos y consultas |
| Orquestación | LangGraph 1.2 | Grafo Corrective RAG (`retrieve`, `grade_evidence`, `rewrite_query`, `generate`) |
| Orquestación | LangChain 1.4 y langchain-core 1.7 | Mensajes, documentos, salida estructurada y puertos (`BaseChatModel`, `Embeddings`) |
| Integraciones | langchain-google-genai 4.4 | Cliente de chat y embeddings de Gemini |
| Integraciones | langchain-mongodb 0.12 y PyMongo 4.19 | Adaptador de MongoDB Atlas Vector Search |
| Procesamiento | langchain-text-splitters 1.1 | División de los Markdown por sección (`##`) |
| Base de datos | MongoDB Atlas Vector Search | Índice vectorial con filtro por modelo de embeddings |
| API | Starlette 1.10 y Uvicorn 0.54 | `POST /ask` con CORS y rate limit |
| Configuración | python-dotenv 1.2 | Carga de variables desde `.env` |
| Pruebas | unittest | Pruebas unitarias con dobles de prueba |
| Despliegue | Docker y Railway | Imagen del API y hosting |
