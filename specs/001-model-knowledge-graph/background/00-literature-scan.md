# Literature scan: knowledge graphs, LLMs and MCP in EnergyPlus modelling

Scan date: 2026-11-10. Method: web searches, reading abstracts and search snippets. **No full paper was
read**, so each entry states what the work claims, not what was verified. The 2026 entries are recent enough
that their details should be checked before anyone cites them.

## Conclusion

The three ingredients exist separately, and no published work combines them. None of the work found has an LLM,
through an MCP server, query a graph of a live EnergyPlus model that stays current as the model is edited.
idfkit-mcp already does part of that through its reference resource.

## 1. Knowledge graphs used to build EnergyPlus models (no LLM)

| Work | What it claims | Relevance |
|---|---|---|
| [Knowledge graph-based framework to automate BEM generation using geometric relation checking and HVAC topology establishment](https://www.sciencedirect.com/science/article/pii/S0378778824011514) (Energy and Buildings, 2024) | Builds a graph of HVAC elements from geometry, turns it into an HVAC topology, simplifies that into the form EnergyPlus expects, and emits an EnergyPlus 9.5 model. | Closest precedent for the topology layer. It uses the graph to **generate** models, not to let an agent reason about one. |
| SimModel to [OWL](https://pure.ul.ie/en/publications/representing-simmodel-in-the-web-ontology-language/) and to [RDF graphs](https://pure.ul.ie/en/publications/making-simmodel-information-available-as-rdf-graphs/) | The SimModel schema converted to an OWL ontology, and instance files to RDF that can be linked to IFC. | Pre-LLM semantic-web work. It notes that EnergyPlus uses a custom schema (IDD), not XSD or EXPRESS. |
| [DAREED project](https://springerlink.bibliotecabuap.elogim.com/chapter/10.1007/978-3-319-73805-5_31) | Ontology concepts derived from the EnergyPlus data dictionary, with an extension of the Semantic Sensor Network ontology. | District scale, pre-LLM. |
| EFOnt, as [cited in arXiv 2509.01459](https://arxiv.org/html/2509.01459v2) | An ontology oriented to EnergyPlus and built around what simulation needs as input. | Shows the gap between simulation ontologies and the operational ones (Brick). |
| [Survey on semantic modeling for building energy management](https://arxiv.org/pdf/2404.11716) (2024) | RDF and OWL as the core stack for linking building, device and simulation data. | Context. |

## 2. LLM agents for EnergyPlus that use structured knowledge (mostly not graphs)

| Work | What it claims | Relevance |
|---|---|---|
| [Knowledge-Guided Self-Reflection LLM Agents for HVAC Simulation in EnergyPlus](https://doi.org/10.1145/3744256.3812593) (ACM) | A graph-structured knowledge base, built from OpenStudio Measure definitions, records parameter dependencies that the natural-language descriptions do not. It lets an agent turn plain-language HVAC instructions into Measure configurations. | **Clearest graph + LLM + EnergyPlus example.** The graph is over the editing tools, not over the building model. |
| [Knowledge-based multi-agent system for automated BEM and simulation service](https://www.sciencedirect.com/science/article/abs/pii/S0378778826007486) (Energy and Buildings, 2026) | A five-category knowledge base (agent description, procedure, rule, example, domain knowledge) that agents use to generate IDFs, fix errors and analyse results at urban scale. | Curated knowledge, close in spirit to the standards layer, but not a graph. |
| [Advancing BEM with LLMs](https://arxiv.org/pdf/2402.09579) (Zhang, Chen and Ford; Energy and Buildings, 2024) | A multi-agent IDF generator with a debugging agent whose fixes are mostly **wrong object references**. | Indirect evidence for graph-checked references, the failure mode idfkit's reference graph prevents. |
| [LLM-driven BEM generation](https://www.sciencedirect.com/science/article/abs/pii/S0378778826003154) (Energy and Buildings, 2026) | LoRA fine-tuning to generate simulation-ready IDF files from free text. | Generation, no graph. |
| [Automatic BEM development and debugging](https://www.osti.gov/servlets/purl/2480816) (OSTI) | An agentic IDF generation and debugging workflow. | Debugging from ERR text. |
| [LLMs for HVAC operations: a critical review](https://arxiv.org/pdf/2609.05314) (2026) | Notes that debugging agents exist but are immature. | Context. |

## 3. MCP servers for EnergyPlus (tool-based; no graph)

| Server | Notes |
|---|---|
| EnergyPlus-MCP, LBNL ([SoftwareX 2025](https://www.sciencedirect.com/science/article/pii/S2352711025003334), [OSTI code](https://www.osti.gov/biblio/code-167294)) | About 35 tools. It argues that structured tool access gives more reliable results than letting an LLM edit model text. The same group published an [MCP-enabled agentic workflow paper](https://www.osti.gov/pages/biblio/3363609-mcp-enabled-agentic-ai-workflow-building-energy-modelling-framework-use-cases). |
| Community servers: [tsbyq](https://lobehub.com/mcp/tsbyq-energyplus_mcp), [EnergyPlus-MCP-epjson](https://github.com/ericmartinpe/EnergyPlus-MCP-epjson), [energyplus-idf-mcp-server](https://github.com/walkererik1991/energyplus-idf-mcp-server), [energyplus-mcp-server-sim](https://github.com/arnebrooks96/energyplus-mcp-server-sim), proofs of concept ([IntelliGrid](https://glama.ai/mcp/servers/shankar-mallidi/IntelliGrid-AI-Powered-Building-Energy-Optimization), [Akki-24](https://glama.ai/mcp/servers/Akki-24/Autonomous-Building-Energy-Optimization-PoC-with-MCP-and-EnergyPlus)) | Load, edit, validate and simulate tools. None found describing a model graph. |
| [idfkit-mcp](https://github.com/idfkit/idfkit-mcp) (this repository) | Already exposes the model's reference graph to the LLM (`idfkit://model/references/{name}`, `get_available_references`). No other EnergyPlus MCP server was found doing that. |

## 4. Graphs plus LLMs in building operations (the strongest evidence that graphs help)

| Work | What it claims | Relevance |
|---|---|---|
| [BuildingGPT](https://www.sciencedirect.com/science/article/abs/pii/S0360132325013253) (Building and Environment, 2025) | Mixed vector and graph retrieval over Brick models. 45 models, 18,555 questions, 20–40% better than baselines. **Pasting the whole ontology into the prompt helped little.** | Supports giving the agent targeted graph queries as tools, rather than the whole graph. This is a design input for every layer in this spec. |
| [BuildingGPT follow-up](https://www.sciencedirect.com/science/article/abs/pii/S0926580525007782) (Automation in Construction) | Adds fine-tuning, chain-of-thought and SPARQL access. | Context. |
| [ThermoLLM](https://arxiv.org/html/2606.22911) (2026) | A spatial knowledge graph derived from Brick as context for an LLM choosing zone setpoints. | Context. |
| [PV-GPT](https://www.sciencedirect.com/science/article/abs/pii/S235271022502772X) | Brick plus structured prompts for querying energy data. | Context. |

Nothing was found on **ASHRAE 223P with LLMs**, and no Brick-to-EnergyPlus or EnergyPlus-to-Brick converter turned
up. Report 02 confirms the second point more thoroughly.

## What this means for the feature

1. The combination this feature proposes (agent ↔ MCP ↔ live typed model graph, with results and standards attached)
   is **unpublished**. The evaluation in this spec could be a publishable result.
2. The evidence lines up with the three layers. Topology has a non-LLM precedent. Results on the graph has none.
   Ontology links are proven useful to LLMs on the operations side (Brick), but nobody has bridged them to EnergyPlus.
3. Wrong references are the most commonly reported LLM failure, and graph checks are the known remedy.
4. No study measures whether any of this improves an agent's diagnosis. That is why this spec includes an evaluation.
