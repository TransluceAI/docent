# Investigator Module

The Investigator module is a system for performing experiments on language model behaviors. It enables users to systematically investigate when and how specific LLM behaviors manifest by varying contexts and measuring responses. See the [design document](https://docs.google.com/document/d/1CKqyiTUvsW9gktMKcLB8y6BWux9eIZgQIfVli3O5T58/edit?tab=t.doyvs6b1xb3) for goals and motivation.

## 📋 Table of Contents
- [Overview](#overview)
- [Architecture](#architecture)
  - [Backend](#backend)
  - [Frontend](#frontend)
  - [Database Schema](#database-schema)
  - [Workers and Job Processing](#workers-and-job-processing)
- [Core Concepts](#core-concepts)
- [Experiment Types](#experiment-types)
- [API Reference](#api-reference)
- [Integration with Docent](#integration-with-docent)

## Overview

**Objective**: Build a system that enables users to investigate in what contexts known medium-tail language model behaviors occur, and what forms they can take.

The Investigator achieves this by providing tools for:
- Creating controlled experiments on language models
- Systematically varying contexts to test behavior sensitivity
- Evaluating model responses with configurable judges
- Storing and analyzing results in Docent collections

### Key Features
- **Workspaces**: Self-contained environments for organizing experiments, analogous to collections in Docent
- **Configurable Components**: Reusable base contexts, judges, experiment ideas, and model backends
- **Streaming Architecture**: Real-time updates for long-running experiments via Redis and SSE
- **Integration with Docent**: Automatic storage of agent runs in Docent collections for analysis

## Architecture

### Backend

The backend is located at `docent_core/investigator/` and consists of several key components:

#### Core Services (`services/`)
- **`InvestigatorMonoService`**: Main service handling CRUD operations for workspaces, configs, and experiments
- **`CounterfactualService`**: Manages counterfactual experiment lifecycle, job creation, and result storage

#### Database Layer (`db/`)
- **Schemas**: SQLAlchemy models for workspaces, experiments, judges, and backends
- **Contexts**: `WorkspaceContext` for scoping operations to specific workspaces

#### Tools (`tools/`)
The tools directory contains the core experiment implementations:

- **`backends/`**: OpenAI-compatible backend configurations for model access
- **`contexts/`**: Base context definitions (prompts that trigger behaviors)
- **`judges/`**: Evaluation modules including:
  - `RubricJudge`: LLM-based evaluation using custom rubrics
  - `ConstantJudge`: Baseline judge for testing
- **`subject_models/`**: Wrappers for models being investigated
- **`policies/`**: Deterministic context policies for experiment variations
- **`rollout/`**: Interaction streaming and management
- **`counterfactual_analysis/`**: Core counterfactual experiment logic

#### Workers (`workers/`)
- **`counterfactual_experiment_worker.py`**: Handles long-running experiment execution
  - Streams updates via Redis
  - Manages subscriptions for specific agent runs
  - Stores completed results in Docent collections

#### Utilities (`utils/`)
Advanced async utilities for managing concurrent operations:
- **`async_util/`**: Background loops, thread management, concurrency limiters
- **`extraction_util.py`**: JSON extraction from LLM responses

#### REST API (`server/rest/`)
FastAPI endpoints at `/api/investigator/` providing:
- Workspace management
- Component CRUD operations (judges, backends, ideas, contexts)
- Experiment configuration and execution
- Real-time streaming via SSE

### Frontend

The frontend is located at `docent_core/_web/app/investigator/` and provides:

#### Main Pages
- **`/investigator`**: Dashboard listing all workspaces
- **`/investigator/[workspace_id]`**: Workspace view with experiment management

#### Key Components (`[workspace_id]/components/`)
- **`LeftSidebar`**: Experiment list and selection
- **`TopPanel`**: Experiment configuration display
- **`MainPanel`**: Primary content area
- **`CounterfactualExperimentViewer`**: Real-time experiment visualization
- **`ExperimentStreamManager`**: SSE connection management
- **Component Editors**: Forms for creating/editing base contexts, judges, ideas, and backends

#### State Management
- Redux store for experiment state (`experimentViewerSlice`)
- RTK Query for API interactions (`investigatorApi`)
- Real-time updates via SSE subscriptions

### Database Schema

The investigator uses PostgreSQL with the following main tables:

#### `investigator_workspaces`
- Primary container for experiments
- Links to user who created it
- Has many: judges, backends, ideas, contexts, experiments

#### `counterfactual_experiment_configs`
- Configuration for a specific experiment
- References: workspace, judge, backend, idea, base_context
- Parameters: num_counterfactuals, num_replicas, max_turns

#### `counterfactual_experiment_results`
- Stores completed experiment results
- Contains: experiment summary, metadata, docent_collection_id
- Links to agent runs stored in Docent

#### `judge_configs`
- Rubric-based evaluation configurations
- Contains: name, rubric text, workspace_id

#### `openai_compatible_backends`
- Model provider configurations
- Supports: OpenAI, Anthropic, Google, local models
- Stores: API keys, base URLs, model names

#### `experiment_ideas`
- High-level descriptions of what to vary
- Example: "Change the language of the prompt to test multilingual behavior"

#### `base_contexts`
- Starting prompts that trigger target behaviors
- Stored as JSON arrays of messages

### Workers and Job Processing

The investigator uses a Redis-based job queue system integrated with Docent's worker infrastructure:

1. **Job Creation**: REST API enqueues jobs via `CounterfactualService`
2. **Worker Execution**: `counterfactual_experiment_worker` processes jobs
3. **Streaming Updates**: Results streamed to Redis, consumed by frontend via SSE
4. **Result Storage**: Completed experiments stored in database with agent runs in Docent collections

## Core Concepts

### Workspaces
Self-contained environments for organizing related experiments. Each workspace contains:
- Base contexts (prompts)
- Judge configurations
- Model backends
- Experiment ideas
- Experiment configurations and results

### Base Contexts
Starting prompts or conversations that reliably trigger the behavior you want to study. Stored as message arrays with roles (system/user/assistant).

### Judges
Evaluation modules that assess whether a behavior was exhibited:
- **Rubric Judge**: Uses an LLM with a custom rubric to score responses
- **Constant Judge**: Returns fixed scores (useful for baselines)

### Experiment Ideas
High-level descriptions of variations to test, e.g.:
- "Change the tone to be more formal"
- "Translate key terms to another language"
- "Add contradictory information"

### Model Backends
Configurations for accessing LLMs:
- Supports OpenAI, Anthropic, Google, and OpenAI-compatible endpoints
- Stores API credentials and model selection

## Experiment Types

### CounterfactualExperiment
Currently the primary experiment type, which:

1. **Generates Variations**: Takes a base context and experiment idea, generates N counterfactual contexts
2. **Applies Counterfactuals**: Creates modified versions of the base context
3. **Runs Rollouts**: Executes base + counterfactual contexts with the subject model
4. **Evaluates Responses**: Uses the configured judge to score each response
5. **Stores Results**: Saves agent runs to Docent collections for analysis

#### Experiment Flow
```
Base Context + Idea → Generate Counterfactuals → Apply to Context →
→ Run Rollouts → Judge Responses → Store in Docent
```

## API Reference

### Workspace Endpoints
- `POST /workspaces` - Create workspace
- `GET /workspaces` - List user's workspaces
- `GET /workspaces/{id}` - Get workspace details
- `DELETE /workspaces/{id}` - Delete workspace

### Component Endpoints
Each component type (judge-configs, openai-compatible-backends, experiment-ideas, base-contexts) supports:
- `POST /workspaces/{workspace_id}/{component}` - Create
- `GET /workspaces/{workspace_id}/{component}` - List
- `DELETE /{component}/{id}` - Delete

### Experiment Endpoints
- `POST /workspaces/{workspace_id}/experiment-configs` - Create configuration
- `GET /workspaces/{workspace_id}/experiment-configs` - List configurations
- `POST /experiment-configs/{id}/start` - Start experiment
- `POST /experiment-configs/{id}/cancel` - Cancel running experiment
- `GET /experiment-configs/{id}/stream` - SSE stream for updates
- `GET /experiment-results/{id}` - Get completed results

## Integration with Docent

Intersection with the main Docent platform:

### Agent Run Storage
- Each completed experiment creates a Docent collection
- All agent runs are stored as Docent agent runs
- Includes metadata linking runs to their counterfactual variations

## Development

### Adding a New Experiment Type
1. Create experiment logic in `tools/[experiment_name]/`
2. Add database schema in `db/schemas/`
3. Implement worker in `workers/`
4. Add service methods in `services/`
5. Create REST endpoints in `server/rest/`
6. Build frontend components in `_web/app/investigator/`

### Testing
Run tests with: `pytest tests/unit/investigator/`
